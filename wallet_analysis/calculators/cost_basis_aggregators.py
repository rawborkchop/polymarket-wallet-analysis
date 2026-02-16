"""
Aggregators for cost-basis PnL calculation.

Groups RealizedPnLEvents by market and by day for reporting.
"""

from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Any

from .position_tracker import RealizedPnLEvent

ZERO = Decimal('0')


class CostBasisMarketAggregator:
    """Groups realized PnL events by market_id."""

    def aggregate(self, events: List[RealizedPnLEvent]) -> List[Dict[str, Any]]:
        """
        Aggregate realized PnL events by market.

        Returns list of dicts sorted by absolute PnL descending.
        """
        by_market: Dict[str, Decimal] = defaultdict(lambda: ZERO)
        for event in events:
            key = str(event.market_id) if event.market_id else 'unknown'
            by_market[key] += event.amount

        results = []
        for market_id, pnl in by_market.items():
            results.append({
                'market_id': market_id if market_id != 'unknown' else None,
                'pnl': float(pnl),
            })

        results.sort(key=lambda x: abs(x['pnl']), reverse=True)
        return results


class CostBasisDailyAggregator:
    """Groups realized PnL events by date with cumulative tracking."""

    def aggregate(self, events: List[RealizedPnLEvent]) -> List[Dict[str, Any]]:
        """
        Aggregate realized PnL events by date.

        Returns list of dicts sorted chronologically with cumulative PnL.
        """
        by_date: Dict[Any, Decimal] = defaultdict(lambda: ZERO)
        for event in events:
            day = event.datetime.date()
            by_date[day] += event.amount

        sorted_dates = sorted(by_date.keys())
        cumulative = ZERO
        results = []

        for day in sorted_dates:
            day_pnl = by_date[day]
            cumulative += day_pnl
            results.append({
                'date': day,
                'daily_pnl': float(day_pnl),
                'cumulative_pnl': float(cumulative),
            })

        return results
