"""
Aggregators for P&L calculation.

Follows Single Responsibility Principle (SRP):
Each aggregator has one job - aggregate data in a specific dimension.
"""

from decimal import Decimal
from collections import defaultdict
from typing import Dict, List, Any

from .interfaces import IAggregator


class CashFlowEntry:
    """Data class for cash flow components."""

    __slots__ = ['buys', 'sells', 'redeems', 'merges', 'splits', 'rewards', 'conversions', 'volume', 'trade_count']

    def __init__(self):
        self.buys = Decimal('0')
        self.sells = Decimal('0')
        self.redeems = Decimal('0')
        self.merges = Decimal('0')
        self.splits = Decimal('0')
        self.rewards = Decimal('0')
        self.conversions = Decimal('0')
        self.volume = Decimal('0')
        self.trade_count = 0

    @property
    def inflows(self) -> Decimal:
        """Total money coming in: sells + redeems + merges + rewards (NOT conversions)"""
        return self.sells + self.redeems + self.merges + self.rewards

    @property
    def outflows(self) -> Decimal:
        """Total money going out: buys + splits"""
        return self.buys + self.splits

    @property
    def pnl(self) -> Decimal:
        """Net P&L: inflows - outflows"""
        return self.inflows - self.outflows

    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary with float values for JSON."""
        return {
            'buys': float(self.buys),
            'sells': float(self.sells),
            'redeems': float(self.redeems),
            'merges': float(self.merges),
            'splits': float(self.splits),
            'rewards': float(self.rewards),
            'conversions': float(self.conversions),
            'volume': float(self.volume),
            'trade_count': self.trade_count,
        }


class MarketAggregator(IAggregator):
    """
    Aggregates cash flows by market.

    Useful for P&L breakdown per market/condition.
    """

    def __init__(self):
        self._flows: Dict[str, CashFlowEntry] = defaultdict(CashFlowEntry)

    def add_trade(self, trade: Any) -> None:
        """Add a trade to market aggregation."""
        market_id = getattr(trade, 'market_id', None) or 'unknown'
        value = Decimal(str(trade.total_value))

        entry = self._flows[market_id]
        entry.volume += value
        entry.trade_count += 1

        if trade.side == 'BUY':
            entry.buys += value
        elif trade.side == 'SELL':
            entry.sells += value

    def add_activity(self, activity: Any) -> None:
        """Add an activity to market aggregation."""
        market_id = getattr(activity, 'market_id', None) or 'unknown'
        usdc = Decimal(str(activity.usdc_size))

        entry = self._flows[market_id]

        activity_type = activity.activity_type
        if activity_type == 'REDEEM':
            entry.redeems += usdc
        elif activity_type == 'MERGE':
            entry.merges += usdc
        elif activity_type == 'SPLIT':
            entry.splits += usdc
        elif activity_type == 'REWARD':
            entry.rewards += usdc
        elif activity_type == 'CONVERSION':
            entry.conversions += usdc

    def get_results(self) -> Dict[str, Any]:
        """Get P&L breakdown by market."""
        results = []
        for market_id, entry in self._flows.items():
            result = entry.to_dict()
            result['market_id'] = market_id
            result['pnl'] = float(entry.pnl)
            results.append(result)

        # Sort by absolute P&L
        results.sort(key=lambda x: abs(x['pnl']), reverse=True)
        return {'pnl_by_market': results}

    def get_totals(self) -> CashFlowEntry:
        """Get combined totals across all markets."""
        totals = CashFlowEntry()
        for entry in self._flows.values():
            totals.buys += entry.buys
            totals.sells += entry.sells
            totals.redeems += entry.redeems
            totals.merges += entry.merges
            totals.splits += entry.splits
            totals.rewards += entry.rewards
            totals.conversions += entry.conversions
            totals.volume += entry.volume
            totals.trade_count += entry.trade_count
        return totals


class DailyAggregator(IAggregator):
    """
    Aggregates cash flows by day.

    Useful for timeline charts and daily P&L tracking.
    """

    def __init__(self):
        self._flows: Dict[Any, CashFlowEntry] = defaultdict(CashFlowEntry)

    def add_trade(self, trade: Any) -> None:
        """Add a trade to daily aggregation."""
        date = trade.datetime.date()
        value = Decimal(str(trade.total_value))

        entry = self._flows[date]
        entry.volume += value
        entry.trade_count += 1

        if trade.side == 'BUY':
            entry.buys += value
        elif trade.side == 'SELL':
            entry.sells += value

    def add_activity(self, activity: Any) -> None:
        """Add an activity to daily aggregation."""
        date = activity.datetime.date()
        usdc = Decimal(str(activity.usdc_size))

        entry = self._flows[date]

        activity_type = activity.activity_type
        if activity_type == 'REDEEM':
            entry.redeems += usdc
        elif activity_type == 'MERGE':
            entry.merges += usdc
        elif activity_type == 'SPLIT':
            entry.splits += usdc
        elif activity_type == 'REWARD':
            entry.rewards += usdc
        elif activity_type == 'CONVERSION':
            entry.conversions += usdc

    def get_results(self) -> Dict[str, Any]:
        """Get daily P&L with cumulative tracking."""
        sorted_dates = sorted(self._flows.keys())
        cumulative = Decimal('0')
        daily_pnl_list = []

        for date in sorted_dates:
            entry = self._flows[date]
            day_pnl = entry.pnl
            cumulative += day_pnl

            result = entry.to_dict()
            result['date'] = date
            result['daily_pnl'] = float(day_pnl)
            result['cumulative_pnl'] = float(cumulative)
            daily_pnl_list.append(result)

        return {'daily_pnl': daily_pnl_list}

    def get_dates(self) -> List[Any]:
        """Get sorted list of dates with data."""
        return sorted(self._flows.keys())
