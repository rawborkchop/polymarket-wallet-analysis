from abc import ABC, abstractmethod
from typing import List, Optional, Dict

from src.api.models import Trade


class ITradeFetcher(ABC):
    """Interface for fetching trades from a data source (Interface Segregation Principle)."""

    @abstractmethod
    def fetch_trades(self, wallet_address: str, limit: int = 100) -> List[Trade]:
        """Fetch trades for a given wallet address."""
        pass

    @abstractmethod
    def fetch_all_trades(
        self,
        wallet_address: str,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
    ) -> List[Trade]:
        """Fetch all trades for a given wallet address with pagination."""
        pass

    @abstractmethod
    def fetch_all_activity(
        self,
        wallet_address: str,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
    ) -> Dict[str, List[dict]]:
        """Fetch all activity types (TRADE, REDEEM, etc.) for a wallet."""
        pass
