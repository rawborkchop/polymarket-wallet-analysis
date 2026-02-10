"""
P&L Calculator - SINGLE SOURCE OF TRUTH for P&L calculation.

This module implements the IPnLCalculator interface and provides
the authoritative P&L calculation for the entire system.

Formula: P&L = (sells + redeems + merges + rewards) - (buys + splits)

Follows SOLID principles:
- Single Responsibility: Only calculates P&L
- Open/Closed: Extensible via aggregators
- Dependency Inversion: Depends on abstractions (interfaces)
"""

from decimal import Decimal
from typing import Dict, Any, Optional, List
from datetime import date
import logging

from .interfaces import IPnLCalculator, ICashFlowProvider
from .aggregators import MarketAggregator, DailyAggregator, CashFlowEntry

logger = logging.getLogger(__name__)


class DjangoCashFlowProvider(ICashFlowProvider):
    """
    Cash flow provider using Django ORM.

    Implements ICashFlowProvider to abstract database access.
    """

    def get_trades(self, wallet) -> List[Any]:
        """Get all trades for a wallet from Django ORM."""
        return list(wallet.trades.select_related('market').order_by('timestamp'))

    def get_activities(self, wallet) -> List[Any]:
        """Get all activities for a wallet from Django ORM."""
        return list(wallet.activities.select_related('market').order_by('timestamp'))


class PnLCalculator(IPnLCalculator):
    """
    Main P&L calculator implementation.

    This is the SINGLE SOURCE OF TRUTH for P&L in the system.
    All other parts of the codebase should use this calculator
    for P&L values.
    """

    def __init__(self, cash_flow_provider: Optional[ICashFlowProvider] = None):
        """
        Initialize calculator with optional cash flow provider.

        Args:
            cash_flow_provider: Provider for trade/activity data.
                               Defaults to DjangoCashFlowProvider.
        """
        self._provider = cash_flow_provider or DjangoCashFlowProvider()

    def calculate(self, wallet) -> Dict[str, Any]:
        """
        Calculate P&L for a wallet.

        P&L = (sells + redeems + merges + rewards) - (buys + splits)

        Returns comprehensive P&L data including:
        - total_realized_pnl: Net P&L amount
        - daily_pnl: Timeline of daily P&L
        - pnl_by_market: Breakdown by market
        - totals: Summary of all cash flow components
        """
        # Get data from provider
        trades = self._provider.get_trades(wallet)
        activities = self._provider.get_activities(wallet)

        # Initialize aggregators
        market_agg = MarketAggregator()
        daily_agg = DailyAggregator()

        # Process trades
        for trade in trades:
            market_agg.add_trade(trade)
            daily_agg.add_trade(trade)

        # Process activities
        for activity in activities:
            market_agg.add_activity(activity)
            daily_agg.add_activity(activity)

        # Get results
        totals = market_agg.get_totals()
        market_results = market_agg.get_results()
        daily_results = daily_agg.get_results()

        return {
            'total_realized_pnl': float(totals.pnl),
            'daily_pnl': daily_results['daily_pnl'],
            'pnl_by_market': market_results['pnl_by_market'][:20],
            'totals': {
                'total_buys': float(totals.buys),
                'total_sells': float(totals.sells),
                'total_redeems': float(totals.redeems),
                'total_merges': float(totals.merges),
                'total_splits': float(totals.splits),
                'total_rewards': float(totals.rewards),
                'total_conversions': float(totals.conversions),
                'total_inflows': float(totals.inflows),
                'total_outflows': float(totals.outflows),
            },
        }

    def _aggregate(self, trades, activities):
        """
        Run aggregation on given trades and activities.

        Returns (market_agg, daily_agg) tuple of aggregator instances.
        """
        market_agg = MarketAggregator()
        daily_agg = DailyAggregator()

        for trade in trades:
            market_agg.add_trade(trade)
            daily_agg.add_trade(trade)

        for activity in activities:
            market_agg.add_activity(activity)
            daily_agg.add_activity(activity)

        return market_agg, daily_agg

    def calculate_filtered(
        self,
        wallet,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Calculate P&L for a specific date range.

        Filters trades and activities BEFORE aggregation so that
        pnl_by_market, daily_pnl, and totals all reflect only the filtered period.
        """
        trades = self._provider.get_trades(wallet)
        activities = self._provider.get_activities(wallet)

        if not start_date and not end_date:
            # No filter — use full calculation
            return self.calculate(wallet)

        # Also compute full P&L for reference
        full_result = self.calculate(wallet)

        # Filter by date range
        if start_date:
            trades = [t for t in trades if t.datetime.date() >= start_date]
            activities = [a for a in activities if a.datetime.date() >= start_date]
        if end_date:
            trades = [t for t in trades if t.datetime.date() <= end_date]
            activities = [a for a in activities if a.datetime.date() <= end_date]

        # Aggregate only filtered data
        market_agg, daily_agg = self._aggregate(trades, activities)

        totals = market_agg.get_totals()
        market_results = market_agg.get_results()
        daily_results = daily_agg.get_results()

        return {
            'total_realized_pnl': float(totals.pnl),
            'daily_pnl': daily_results['daily_pnl'],
            'pnl_by_market': market_results['pnl_by_market'][:20],
            'totals': {
                'total_buys': float(totals.buys),
                'total_sells': float(totals.sells),
                'total_redeems': float(totals.redeems),
                'total_merges': float(totals.merges),
                'total_splits': float(totals.splits),
                'total_rewards': float(totals.rewards),
                'total_conversions': float(totals.conversions),
                'total_inflows': float(totals.inflows),
                'total_outflows': float(totals.outflows),
            },
            'filtered_range': {
                'start': str(start_date) if start_date else None,
                'end': str(end_date) if end_date else None,
            },
            'full_period_pnl': full_result['total_realized_pnl'],
        }


# Module-level functions for backward compatibility
_default_calculator = None


def _get_calculator() -> PnLCalculator:
    """Get or create the default calculator instance."""
    global _default_calculator
    if _default_calculator is None:
        _default_calculator = PnLCalculator()
    return _default_calculator


def calculate_wallet_pnl(wallet) -> Dict[str, Any]:
    """
    Calculate P&L for a wallet.

    This is a convenience function that uses the default calculator.
    For custom providers, instantiate PnLCalculator directly.
    """
    return _get_calculator().calculate(wallet)


def calculate_wallet_pnl_filtered(
    wallet,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Calculate P&L for a specific date range.

    This is a convenience function that uses the default calculator.
    """
    return _get_calculator().calculate_filtered(wallet, start_date, end_date)
