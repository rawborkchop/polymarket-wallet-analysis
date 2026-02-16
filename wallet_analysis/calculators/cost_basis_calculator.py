"""
Cost Basis PnL Calculator — Weighted Average Cost Basis method.

Implements IPnLCalculator using per-position cost basis tracking
to calculate realized PnL. This matches Polymarket's official
Data API and PnL subgraph methodology.
"""

from decimal import Decimal
from typing import Dict, Any, Optional, List
from datetime import date
import logging

from .interfaces import IPnLCalculator, ICashFlowProvider
from .pnl_calculator import DjangoCashFlowProvider, PnLCalculator
from .position_tracker import PositionTracker
from .cost_basis_aggregators import CostBasisMarketAggregator, CostBasisDailyAggregator

logger = logging.getLogger(__name__)

ZERO = Decimal('0')


class CostBasisPnLCalculator(IPnLCalculator):
    """
    PnL calculator using weighted average cost basis.

    Processes all trades and activities chronologically to build
    per-position cost basis and compute realized PnL.
    """

    def __init__(self, cash_flow_provider: Optional[ICashFlowProvider] = None):
        self._provider = cash_flow_provider or DjangoCashFlowProvider()
        self._tracker = PositionTracker()
        self._market_agg = CostBasisMarketAggregator()
        self._daily_agg = CostBasisDailyAggregator()
        # Keep cash flow calculator for comparison
        self._cashflow_calc = PnLCalculator(cash_flow_provider=self._provider)

    def calculate(self, wallet) -> Dict[str, Any]:
        """
        Calculate PnL for a wallet using cost basis method.

        Returns dict with cost-basis realized PnL, unrealized PnL,
        daily/market breakdowns, and cash flow PnL for comparison.
        """
        trades = self._provider.get_trades(wallet)
        activities = self._provider.get_activities(wallet)

        return self._compute(wallet, trades, activities)

    def calculate_filtered(
        self,
        wallet,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Calculate PnL for a date range.

        Processes ALL events chronologically to build correct cost basis,
        but only reports realized PnL from events within the date range.
        """
        trades = self._provider.get_trades(wallet)
        activities = self._provider.get_activities(wallet)

        if not start_date and not end_date:
            return self._compute(wallet, trades, activities)

        # Process ALL events to build correct cost basis
        market_resolutions = self._build_market_resolutions(activities)
        db_market_assets = self._build_db_market_assets(wallet)
        positions, all_events = self._tracker.process_events(
            trades, activities, market_resolutions,
            db_market_assets=db_market_assets,
        )

        # Filter realized events to the date range
        filtered_events = []
        for event in all_events:
            event_date = event.datetime.date()
            if start_date and event_date < start_date:
                continue
            if end_date and event_date > end_date:
                continue
            filtered_events.append(event)

        # Also compute full-period PnL for reference
        full_realized = sum((e.amount for e in all_events), ZERO)

        # Aggregate filtered events
        filtered_realized = sum((e.amount for e in filtered_events), ZERO)
        market_breakdown = self._market_agg.aggregate(filtered_events)
        daily_breakdown = self._daily_agg.aggregate(filtered_events)

        # Unrealized PnL from current positions
        unrealized = self._compute_unrealized_pnl(wallet)
        open_value = self._compute_open_position_value(wallet)

        # Cash flow comparison for the same filter
        cashflow_result = self._cashflow_calc.calculate_filtered(
            wallet, start_date, end_date
        )

        return {
            'total_realized_pnl': float(filtered_realized),
            'total_unrealized_pnl': float(unrealized),
            'open_position_value': float(open_value),
            'total_pnl': float(filtered_realized + unrealized),
            'cash_flow_pnl': cashflow_result['total_realized_pnl'],
            'daily_pnl': daily_breakdown,
            'pnl_by_market': market_breakdown[:20],
            'positions': self._format_positions(positions),
            'totals': cashflow_result.get('totals', {}),
            'filtered_range': {
                'start': str(start_date) if start_date else None,
                'end': str(end_date) if end_date else None,
            },
            'full_period_pnl': float(full_realized),
        }

    @staticmethod
    def _build_db_market_assets(wallet) -> Dict[str, Dict[str, str]]:
        """Build market_id -> {outcome: asset} map from Trade records in DB."""
        from wallet_analysis.models import Trade
        rows = (
            Trade.objects.filter(wallet=wallet)
            .exclude(asset='')
            .exclude(outcome='')
            .values('market_id', 'outcome', 'asset')
            .distinct()
        )
        result: Dict[str, Dict[str, str]] = {}
        for row in rows:
            mid = str(row['market_id'])
            if mid not in result:
                result[mid] = {}
            result[mid][row['outcome']] = row['asset']
        return result

    def _compute(
        self,
        wallet,
        trades: list,
        activities: list,
    ) -> Dict[str, Any]:
        """Core computation shared by calculate() and unfiltered calculate_filtered()."""
        # Cost basis calculation
        market_resolutions = self._build_market_resolutions(activities)
        db_market_assets = self._build_db_market_assets(wallet)
        positions, realized_events = self._tracker.process_events(
            trades, activities, market_resolutions,
            db_market_assets=db_market_assets,
        )

        total_realized = sum((e.amount for e in realized_events), ZERO)
        market_breakdown = self._market_agg.aggregate(realized_events)
        daily_breakdown = self._daily_agg.aggregate(realized_events)

        # Unrealized PnL from current positions
        unrealized = self._compute_unrealized_pnl(wallet)
        open_value = self._compute_open_position_value(wallet)

        # Cash flow method for comparison
        cashflow_result = self._cashflow_calc.calculate(wallet)

        return {
            'total_realized_pnl': float(total_realized),
            'total_unrealized_pnl': float(unrealized),
            'open_position_value': float(open_value),
            'total_pnl': float(total_realized + unrealized),
            'cash_flow_pnl': cashflow_result['total_realized_pnl'],
            'daily_pnl': daily_breakdown,
            'pnl_by_market': market_breakdown[:20],
            'positions': self._format_positions(positions),
            'totals': cashflow_result.get('totals', {}),
        }

    @staticmethod
    def _build_market_resolutions(activities: list) -> Dict[str, str]:
        """
        Build a mapping of market_id -> winning_outcome from the Market model.

        Only includes resolved markets with a known winning outcome.
        """
        from wallet_analysis.models import Market

        market_ids = set()
        for a in activities:
            mid = getattr(a, 'market_id', None)
            if mid:
                market_ids.add(mid)
            else:
                market = getattr(a, 'market', None)
                if market:
                    pk = getattr(market, 'id', None) or getattr(market, 'pk', None)
                    if pk:
                        market_ids.add(pk)

        if not market_ids:
            return {}

        try:
            resolved = Market.objects.filter(
                id__in=market_ids, resolved=True,
            ).exclude(winning_outcome='')
            return {str(m.id): m.winning_outcome for m in resolved}
        except Exception:
            logger.warning("Could not query Market resolutions", exc_info=True)
            return {}

    def _compute_open_position_value(self, wallet) -> Decimal:
        """
        Compute total mark-to-market value of open positions.

        This is the sum of (size * cur_price) for all current positions,
        representing the total current market value of open holdings.
        Polymarket includes this in their PnL display.
        """
        if wallet is None:
            return ZERO

        try:
            current_positions = wallet.current_positions.all()
        except Exception:
            return ZERO

        total_value = ZERO
        for cp in current_positions:
            size = Decimal(str(cp.size))
            cur_price = Decimal(str(cp.cur_price))
            total_value += size * cur_price

        return total_value

    def _compute_unrealized_pnl(self, wallet) -> Decimal:
        """
        Compute unrealized PnL from current open positions.

        Uses the CurrentPosition model which has cur_price from the API.
        """
        if wallet is None:
            return ZERO

        try:
            current_positions = wallet.current_positions.all()
        except Exception:
            return ZERO

        unrealized = ZERO
        for cp in current_positions:
            # unrealized = (current_price - avg_price) * size
            size = Decimal(str(cp.size))
            avg_price = Decimal(str(cp.avg_price))
            cur_price = Decimal(str(cp.cur_price))
            unrealized += (cur_price - avg_price) * size

        return unrealized

    @staticmethod
    def _format_positions(positions: dict) -> List[Dict[str, Any]]:
        """Format PositionState dict for API response."""
        result = []
        for asset, pos in positions.items():
            if pos.total_bought == ZERO and pos.total_sold == ZERO:
                continue
            result.append({
                'asset': pos.asset,
                'market_id': pos.market_id,
                'outcome': pos.outcome,
                'quantity': float(pos.quantity),
                'avg_price': float(pos.avg_price),
                'realized_pnl': float(pos.realized_pnl),
                'total_bought': float(pos.total_bought),
                'total_sold': float(pos.total_sold),
                'total_cost': float(pos.total_cost),
                'total_revenue': float(pos.total_revenue),
            })
        # Sort by absolute realized PnL
        result.sort(key=lambda x: abs(x['realized_pnl']), reverse=True)
        return result
