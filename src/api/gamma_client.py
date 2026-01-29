from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
import requests


class GammaClient:
    """
    Client for Polymarket Gamma API.

    Used to fetch market resolution data.
    """

    BASE_URL = "https://gamma-api.polymarket.com"
    MAX_WORKERS = 10
    BATCH_SIZE = 50  # Max condition_ids per request

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "PolymarketWalletAnalyzer/1.0"
        })
        self._cache: Dict[str, dict] = {}

    def get_market_resolutions(self, condition_ids: List[str]) -> Dict[str, dict]:
        """
        Fetch resolution data for multiple markets.

        Returns dict mapping condition_id to resolution info:
        {
            condition_id: {
                "resolved": bool,
                "winning_outcome": str or None,
                "outcome_prices": dict  # {"Up": 1, "Down": 0}
            }
        }
        """
        # Filter out already cached
        uncached = [cid for cid in condition_ids if cid not in self._cache]

        if uncached:
            self._fetch_markets_parallel(uncached)

        return {cid: self._cache.get(cid, self._empty_resolution()) for cid in condition_ids}

    def _fetch_markets_parallel(self, condition_ids: List[str]) -> None:
        """Fetch markets in parallel batches."""
        # Split into batches
        batches = [
            condition_ids[i:i + self.BATCH_SIZE]
            for i in range(0, len(condition_ids), self.BATCH_SIZE)
        ]

        print(f"      Fetching resolution data for {len(condition_ids)} markets...")

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = {
                executor.submit(self._fetch_batch, batch): batch
                for batch in batches
            }

            completed = 0
            for future in as_completed(futures):
                try:
                    results = future.result()
                    for cid, data in results.items():
                        self._cache[cid] = data
                    completed += len(futures[future])
                    print(f"      Processed {completed}/{len(condition_ids)} markets...", end="\r")
                except Exception:
                    pass

        print(f"      Processed {len(condition_ids)} markets.          ")

    def _fetch_batch(self, condition_ids: List[str]) -> Dict[str, dict]:
        """Fetch a batch of markets."""
        results = {}

        try:
            # Use repeated params format: ?condition_ids=X&condition_ids=Y
            params = [("condition_ids", cid) for cid in condition_ids]
            response = self._session.get(
                f"{self.BASE_URL}/markets",
                params=params,
                timeout=30
            )
            response.raise_for_status()

            for market in response.json():
                cid = market.get("conditionId")
                if cid:
                    results[cid] = self._parse_resolution(market)
        except Exception:
            # Return empty for failed batch
            for cid in condition_ids:
                results[cid] = self._empty_resolution()

        return results

    def _parse_resolution(self, market: dict) -> dict:
        """Parse market data into resolution info."""
        import json

        resolved = market.get("umaResolutionStatus") == "resolved"
        closed = market.get("closed", False)

        outcomes_str = market.get("outcomes", "[]")
        prices_str = market.get("outcomePrices", "[]")

        try:
            outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            prices = [float(p) for p in prices]
        except (json.JSONDecodeError, ValueError):
            outcomes = []
            prices = []

        outcome_prices = {}
        winning_outcome = None

        for i, outcome in enumerate(outcomes):
            if i < len(prices):
                outcome_prices[outcome] = prices[i]
                if prices[i] == 1.0:
                    winning_outcome = outcome

        return {
            "resolved": resolved or closed,
            "winning_outcome": winning_outcome,
            "outcome_prices": outcome_prices,
            "closed": closed,
        }

    def _empty_resolution(self) -> dict:
        """Return empty resolution data for unknown markets."""
        return {
            "resolved": False,
            "winning_outcome": None,
            "outcome_prices": {},
            "closed": False,
        }
