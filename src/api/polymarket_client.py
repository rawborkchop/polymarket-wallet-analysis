from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Dict

import requests

from src.api.models import Trade
from src.interfaces.trade_fetcher import ITradeFetcher


class PolymarketClient(ITradeFetcher):
    """
    Client for Polymarket Data API.

    Uses /activity endpoint with timestamp filtering for reliable pagination.
    The /trades endpoint has offset limit of 10,000 which is insufficient
    for high-volume wallets.
    """

    BASE_URL = "https://data-api.polymarket.com"
    MAX_LIMIT = 500  # Activity endpoint max is 500
    MAX_WORKERS = 10

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "PolymarketWalletAnalyzer/1.0"
        })

    def _fetch_activity_batch(
        self,
        wallet_address: str,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        offset: int = 0,
        activity_types: str = "TRADE",
    ) -> List[dict]:
        """Fetch a single batch of activity using timestamp filtering."""
        params = {
            "user": wallet_address,
            "limit": self.MAX_LIMIT,
            "offset": offset,
            "type": activity_types,
        }
        if start_ts:
            params["start"] = start_ts
        if end_ts:
            params["end"] = end_ts

        response = self._session.get(
            f"{self.BASE_URL}/activity", params=params, timeout=30
        )
        response.raise_for_status()
        return response.json()

    def fetch_trades(
        self,
        wallet_address: str,
        limit: int = MAX_LIMIT,
        offset: int = 0,
        after_timestamp: Optional[int] = None,
    ) -> List[Trade]:
        """Fetch trades for a given wallet address."""
        self._validate_wallet_address(wallet_address)
        raw = self._fetch_activity_batch(wallet_address, start_ts=after_timestamp, offset=offset)
        return [Trade.from_api_response(t) for t in raw[:limit]]

    def fetch_all_trades(
        self,
        wallet_address: str,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
    ) -> List[Trade]:
        """
        Fetch all trades for a wallet within a time window.

        Uses /activity endpoint with timestamp-based cursor pagination to bypass
        the 10,000 offset limit. The endpoint supports start/end timestamp filtering.
        """
        self._validate_wallet_address(wallet_address)

        all_trades: List[dict] = []
        current_end = before_timestamp
        seen_ids = set()  # Deduplicate by transaction hash + timestamp

        print("      Fetching trades from activity endpoint...", end="\r")

        while True:
            # Fetch batch with current time window
            batch = self._fetch_activity_batch(
                wallet_address,
                start_ts=after_timestamp,
                end_ts=current_end,
                offset=0,
            )

            if not batch:
                break

            # Deduplicate and add trades
            new_trades = 0
            oldest_ts = None
            for trade in batch:
                trade_id = f"{trade.get('transactionHash', '')}_{trade.get('timestamp', '')}"
                if trade_id not in seen_ids:
                    seen_ids.add(trade_id)
                    all_trades.append(trade)
                    new_trades += 1

                ts = trade.get("timestamp", 0)
                if oldest_ts is None or ts < oldest_ts:
                    oldest_ts = ts

            print(f"      Fetched {len(all_trades)} trades (batch: {new_trades} new)...", end="\r")

            # If we got fewer than limit, we've exhausted this window
            if len(batch) < self.MAX_LIMIT:
                break

            # Use oldest timestamp as cursor for next batch (subtract 1 to avoid duplicates)
            if oldest_ts and oldest_ts > (after_timestamp or 0):
                current_end = oldest_ts - 1
            else:
                break

            # Safety: if no new trades, we might be stuck
            if new_trades == 0:
                break

        print(f"      Found {len(all_trades)} trades in time window.          ")

        return [Trade.from_api_response(t) for t in all_trades]

    def _fetch_single_activity_type(
        self,
        wallet_address: str,
        activity_type: str,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
    ) -> List[dict]:
        """Fetch all activities of a single type with proper pagination."""
        all_items: List[dict] = []
        current_end = before_timestamp
        seen_ids = set()

        while True:
            batch = self._fetch_activity_batch(
                wallet_address,
                start_ts=after_timestamp,
                end_ts=current_end,
                offset=0,
                activity_types=activity_type,
            )

            if not batch:
                break

            new_count = 0
            oldest_ts = None
            for item in batch:
                item_id = f"{item.get('transactionHash', '')}_{item.get('timestamp', '')}_{item.get('conditionId', '')}"
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    all_items.append(item)
                    new_count += 1

                ts = item.get("timestamp", 0)
                if oldest_ts is None or ts < oldest_ts:
                    oldest_ts = ts

            if len(batch) < self.MAX_LIMIT:
                break

            if oldest_ts and oldest_ts > (after_timestamp or 0):
                current_end = oldest_ts - 1
            else:
                break

            if new_count == 0:
                break

        return all_items

    def fetch_all_activity(
        self,
        wallet_address: str,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
    ) -> Dict[str, List[dict]]:
        """
        Fetch ALL activity types for a wallet (TRADE, REDEEM, SPLIT, MERGE, REWARD).

        Fetches each type SEPARATELY to ensure complete pagination.
        Combined fetching causes pagination issues with interleaved timestamps.
        """
        self._validate_wallet_address(wallet_address)

        result: Dict[str, List[dict]] = {}
        activity_types = ["TRADE", "REDEEM", "SPLIT", "MERGE", "REWARD"]

        print("      Fetching activity types separately...")

        for act_type in activity_types:
            items = self._fetch_single_activity_type(
                wallet_address, act_type, after_timestamp, before_timestamp
            )
            result[act_type] = items
            print(f"      {act_type}: {len(items)} items")

        print(f"      Total: {len(result.get('TRADE', []))} trades, {len(result.get('REDEEM', []))} redeems, "
              f"{len(result.get('SPLIT', []))} splits, {len(result.get('MERGE', []))} merges, "
              f"{len(result.get('REWARD', []))} rewards")

        return result

    def fetch_pnl_from_subgraph(self, wallet_address: str) -> Dict[str, float]:
        """
        Fetch accurate all-time P&L from Polymarket's PnL subgraph.

        The activity API has data limitations and may miss trades.
        The subgraph indexes directly from blockchain and is authoritative.

        Returns:
            Dict with realized_pnl, total_bought, total_positions, tokens_held
        """
        self._validate_wallet_address(wallet_address)

        subgraph_url = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/pnl-subgraph/0.0.14/gn"

        all_positions = []
        skip = 0
        page_size = 500  # Smaller page size to avoid timeouts
        max_retries = 3
        hit_error = False

        print("      Fetching P&L from subgraph...", end="\r")

        while skip < 15000:  # Safety limit
            query = f'''
            {{
              userPositions(first: {page_size}, skip: {skip}, where: {{user: "{wallet_address.lower()}"}}) {{
                realizedPnl
                totalBought
                amount
              }}
            }}
            '''

            success = False
            for retry in range(max_retries):
                try:
                    response = self._session.post(
                        subgraph_url,
                        json={"query": query},
                        timeout=45  # Longer timeout
                    )
                    data = response.json()

                    if "errors" in data:
                        # Timeout or query error, try with smaller offset
                        if retry < max_retries - 1:
                            continue
                        hit_error = True
                        break

                    positions = data.get("data", {}).get("userPositions", [])
                    if not positions:
                        success = True
                        break

                    all_positions.extend(positions)
                    skip += page_size
                    success = True
                    print(f"      Fetching P&L from subgraph... {len(all_positions)} positions", end="\r")
                    break

                except Exception as e:
                    if retry == max_retries - 1:
                        print(f"      Subgraph error after retries: {e}")
                        hit_error = True

            if not success or hit_error:
                break

            # Check if we got fewer than requested (means we're done)
            if len(data.get("data", {}).get("userPositions", [])) < page_size:
                break

        # Values in subgraph are in micro-USDC (6 decimals)
        total_realized_pnl = sum(float(p.get("realizedPnl", 0)) for p in all_positions) / 1e6
        total_bought = sum(float(p.get("totalBought", 0)) for p in all_positions) / 1e6
        tokens_held = sum(float(p.get("amount", 0)) for p in all_positions) / 1e6

        status = "partial" if hit_error else "complete"
        print(f"      Subgraph: {len(all_positions)} positions ({status}), P&L: ${total_realized_pnl:,.2f}          ")

        return {
            "realized_pnl": total_realized_pnl,
            "total_bought": total_bought,
            "tokens_held": tokens_held,
            "total_positions": len(all_positions),
            "complete": not hit_error,
        }

    def fetch_current_positions(self, wallet_address: str) -> List[dict]:
        """
        Fetch current open positions from the /positions endpoint.

        Returns position-level data including currentValue, initialValue, cashPnl.
        """
        self._validate_wallet_address(wallet_address)

        all_positions = []
        offset = 0

        while True:
            response = self._session.get(
                f"{self.BASE_URL}/positions",
                params={"user": wallet_address, "limit": 500, "offset": offset},
                timeout=30,
            )

            if response.status_code != 200:
                break

            data = response.json()
            if not data:
                break

            all_positions.extend(data)

            if len(data) < 500:
                break
            offset += 500

        return all_positions

    @staticmethod
    def _validate_wallet_address(address: str) -> None:
        """Validate Ethereum wallet address format."""
        if not address.startswith("0x"):
            raise ValueError("Wallet address must start with '0x'")
        if len(address) != 42:
            raise ValueError("Wallet address must be 42 characters")
        try:
            int(address[2:], 16)
        except ValueError:
            raise ValueError("Invalid hexadecimal in wallet address")
