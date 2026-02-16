from abc import ABC, abstractmethod
from typing import List, Optional, Dict


class ITradeFetcher(ABC):
    """Interface for fetching trades from a data source (Interface Segregation Principle)."""

    @abstractmethod
    def fetch_all_activity(
        self,
        wallet_address: str,
        after_timestamp: Optional[int] = None,
        before_timestamp: Optional[int] = None,
    ) -> Dict[str, List[dict]]:
        """Fetch all activity types (TRADE, REDEEM, etc.) for a wallet."""
        pass
