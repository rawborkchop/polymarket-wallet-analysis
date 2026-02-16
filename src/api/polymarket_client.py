import logging
from typing import List, Optional, Dict

import requests

logger = logging.getLogger(__name__)

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
    MAX_PAGINATION_ITERATIONS = 200

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
    ) -> List[dict]:
        """Fetch a single batch of activity using timestamp filtering (DESC sort, no type filter)."""
        params = {
            "user": wallet_address,
            "limit": self.MAX_LIMIT,
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC",
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

    def _fetch_activity_with_window_cursor(
        self,
        wallet_address: str,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
    ) -> List[dict]:
        """
        Fetch all activity using DESC timestamp pagination (backward).

        Sorts DESC and advances end = min_ts - 1 after each full batch,
        guaranteeing no overlap between pages without dedup.
        """
        all_items: List[dict] = []
        current_end = before_timestamp

        for iteration in range(1, self.MAX_PAGINATION_ITERATIONS + 1):
            batch = self._fetch_activity_batch(
                wallet_address=wallet_address,
                start_ts=after_timestamp,
                end_ts=current_end,
            )
            if not batch:
                break

            all_items.extend(batch)
            print(f"      Fetched {len(all_items)} items...", end="\r")

            if len(batch) < self.MAX_LIMIT:
                break

            # Advance backward: min timestamp - 1 to avoid duplicates
            min_ts = min(item.get("timestamp", 0) for item in batch)
            current_end = min_ts - 1

            if after_timestamp is not None and current_end < after_timestamp:
                break
        else:
            logger.warning(
                "_fetch_activity_with_window_cursor hit MAX_PAGINATION_ITERATIONS (%s) for %s",
                self.MAX_PAGINATION_ITERATIONS,
                wallet_address,
            )

        return all_items

    def fetch_all_activity(
        self,
        wallet_address: str,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
    ) -> Dict[str, List[dict]]:
        """
        Fetch ALL activity types for a wallet in a single pass.

        Uses DESC backward pagination without type filtering.
        Splits results by type afterward for downstream consumers.
        """
        self._validate_wallet_address(wallet_address)
        print("      Fetching all activity...")

        all_items = self._fetch_activity_with_window_cursor(
            wallet_address, after_timestamp, before_timestamp
        )

        # Split by type
        result: Dict[str, List[dict]] = {
            "TRADE": [], "REDEEM": [], "SPLIT": [], "MERGE": [], "REWARD": [], "CONVERSION": [],
        }
        for item in all_items:
            item_type = item.get("type", "")
            if item_type in result:
                result[item_type].append(item)

        print(f"      Total: {len(result['TRADE'])} trades, {len(result['REDEEM'])} redeems, "
              f"{len(result['SPLIT'])} splits, {len(result['MERGE'])} merges, "
              f"{len(result['REWARD'])} rewards, {len(result['CONVERSION'])} conversions")

        return result

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
