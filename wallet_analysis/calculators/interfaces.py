"""
Interfaces for P&L calculation components.

Follows Dependency Inversion Principle (DIP):
High-level modules should not depend on low-level modules.
Both should depend on abstractions.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Any, Optional
from datetime import date


class ICashFlowProvider(ABC):
    """
    Interface for providing cash flow data.

    Abstracts the data source (could be Django ORM, API, etc.)
    """

    @abstractmethod
    def get_trades(self, wallet) -> List[Any]:
        """Get all trades for a wallet."""
        pass

    @abstractmethod
    def get_activities(self, wallet) -> List[Any]:
        """Get all activities for a wallet."""
        pass


class IPnLCalculator(ABC):
    """
    Interface for P&L calculation.

    Follows Single Responsibility Principle (SRP):
    Only responsible for calculating P&L from cash flows.
    """

    @abstractmethod
    def calculate(self, wallet) -> Dict[str, Any]:
        """
        Calculate P&L for a wallet.

        Returns:
            Dict containing:
            - total_realized_pnl: Total P&L amount
            - daily_pnl: List of daily P&L entries
            - pnl_by_market: P&L breakdown by market
            - totals: Summary of all cash flow components
        """
        pass

    @abstractmethod
    def calculate_filtered(
        self,
        wallet,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """Calculate P&L for a specific date range."""
        pass


class IPositionTracker(ABC):
    """
    Interface for position tracking / cost basis computation.
    """

    @abstractmethod
    def process_events(self, trades: List[Any], activities: List[Any]) -> Any:
        """Process trades and activities to compute per-position state."""
        pass


class IAggregator(ABC):
    """
    Interface for aggregating cash flow data.

    Follows Open/Closed Principle (OCP):
    Open for extension (new aggregation strategies),
    closed for modification.
    """

    @abstractmethod
    def add_trade(self, trade: Any) -> None:
        """Add a trade to the aggregation."""
        pass

    @abstractmethod
    def add_activity(self, activity: Any) -> None:
        """Add an activity to the aggregation."""
        pass

    @abstractmethod
    def get_results(self) -> Dict[str, Any]:
        """Get the aggregated results."""
        pass
