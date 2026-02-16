"""
P&L Calculators — Cash Flow and Cost Basis methods.

This module provides two PnL calculation strategies:
- PnLCalculator (CashFlowPnLCalculator): Cash flow method (inflows - outflows)
- CostBasisPnLCalculator: Weighted Average Cost Basis (WACB) method

The default convenience functions use the cost basis calculator.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Any, Optional, List, Tuple
from datetime import date, timedelta
import logging

from django.utils import timezone

from .interfaces import IPnLCalculator, ICashFlowProvider
from .aggregators import MarketAggregator, DailyAggregator, CashFlowEntry

logger = logging.getLogger(__name__)

ZERO = Decimal('0')
ONE = Decimal('1')
EPS = Decimal('0.000001')


@dataclass
class AvgCostPositionState:
    """In-memory position state keyed by Trade/Activity asset id."""

    asset_id: str
    market_id: Optional[int] = None
    outcome: str = ''
    size: Decimal = ZERO
    avg_cost: Decimal = ZERO
    realized_pnl: Decimal = ZERO


class AvgCostBasisCalculator:
    """
    Position-level average cost basis calculator.

    Rules:
    - BUY updates weighted average cost
    - SELL realizes (sell_price - avg_cost) * size
    - REDEEM with positive value realizes (1 - avg_cost) * size
    - REDEEM loser/value=0: realizes -(avg_cost * size) loss
    - CONVERSION: transfers position from source child to siblings in neg-risk group
    - REWARD is added directly to realized PnL
    - MERGE distributes proceeds across open outcome positions
    """

    PERIOD_WINDOWS = {
        'ALL': None,
        '1M': timedelta(days=31),
        '1W': timedelta(days=7),
        '1D': timedelta(days=1),
    }

    def __init__(self, wallet_id: int):
        self.wallet_id = wallet_id

    @staticmethod
    def _coerce_decimal(value: Any) -> Decimal:
        return Decimal(str(value or 0))

    def _period_start_timestamp(self, period: str) -> Optional[int]:
        window = self.PERIOD_WINDOWS.get(period)
        if window is None:
            return None
        return int((timezone.now() - window).timestamp())

    @staticmethod
    def _event_sort_key(event: Tuple[str, Any]) -> Tuple[int, int, int]:
        event_type, obj = event
        if event_type == 'trade':
            return (obj.timestamp, 0, obj.id)

        if obj.activity_type == 'REDEEM':
            # Winner redeems before loser redeems at the same timestamp.
            if Decimal(str(obj.usdc_size or 0)) > ZERO:
                return (obj.timestamp, 1, obj.id)
            return (obj.timestamp, 3, obj.id)

        if obj.activity_type in ('SPLIT', 'CONVERSION', 'MERGE'):
            return (obj.timestamp, 0, obj.id)

        return (obj.timestamp, 2, obj.id)

    @staticmethod
    def _is_in_period(timestamp: int, period_start_ts: Optional[int]) -> bool:
        return period_start_ts is None or timestamp >= period_start_ts

    @staticmethod
    def _format_daily_pnl(daily_pnl: Dict[str, Decimal]) -> List[Dict[str, float]]:
        cumulative = ZERO
        rows = []
        for day in sorted(daily_pnl.keys()):
            daily_value = daily_pnl[day]
            cumulative += daily_value
            rows.append({
                'date': day,
                'daily_pnl': float(daily_value),
                'cumulative_pnl': float(cumulative),
                'volume': 0.0,
            })
        return rows

    @staticmethod
    def _sorted_market_rows(market_rows: Dict[Any, Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = []
        for market_id, row in market_rows.items():
            rows.append({
                'market_id': market_id,
                'trade_count': row['trade_count'],
                'buys': float(row['buys']),
                'sells': float(row['sells']),
                'redeems': float(row['redeems']),
                'pnl': float(row['pnl']),
            })
        rows.sort(key=lambda r: abs(r['pnl']), reverse=True)
        return rows

    @staticmethod
    def _market_open_positions(
        positions: Dict[str, AvgCostPositionState],
        market_id: Optional[int],
    ) -> List[AvgCostPositionState]:
        if not market_id:
            return []
        return [p for p in positions.values() if p.market_id == market_id and p.size > EPS]

    @staticmethod
    def _position_key(market_id: int, outcome: str) -> str:
        return f"{market_id}:{outcome}"

    @staticmethod
    def _build_neg_risk_groups(wallet) -> Dict[str, List[int]]:
        """Build mapping: neg_risk_market_id → [child market DB ids].

        Also includes the parent market itself (the one with CONVERSIONs).
        Returns empty dict if no neg-risk markets are found.
        """
        from wallet_analysis.models import Market, Trade, Activity

        # All market ids this wallet touches
        trade_mids = set(
            Trade.objects.filter(wallet=wallet)
            .values_list('market_id', flat=True).distinct()
        )
        activity_mids = set(
            Activity.objects.filter(wallet=wallet)
            .values_list('market_id', flat=True).distinct()
        )
        all_mids = trade_mids | activity_mids

        # Fetch neg-risk metadata for these markets
        nr_markets = Market.objects.filter(
            id__in=all_mids, neg_risk=True
        ).exclude(neg_risk_market_id='').values_list('id', 'neg_risk_market_id')

        groups: Dict[str, List[int]] = defaultdict(list)
        for mid, nrmid in nr_markets:
            groups[nrmid].append(mid)

        # Also map parent condition_ids to market ids (for CONVERSION matching)
        # A CONVERSION's market_id is the parent, whose condition_id == neg_risk_market_id
        parent_markets = Market.objects.filter(
            condition_id__in=groups.keys(), id__in=all_mids
        ).values_list('id', 'condition_id')
        for pid, cid in parent_markets:
            if pid not in groups[cid]:
                groups[cid].append(pid)

        return dict(groups)

    @staticmethod
    def _build_parent_to_group(neg_risk_groups, wallet) -> Dict[int, str]:
        """Map parent market_id (CONVERSION target) → neg_risk_market_id."""
        from wallet_analysis.models import Market
        parent_cids = set(neg_risk_groups.keys())
        result = {}
        for m in Market.objects.filter(condition_id__in=parent_cids):
            result[m.id] = m.condition_id
        return result

    @staticmethod
    def _build_child_to_group(neg_risk_groups) -> Dict[int, str]:
        """Map child market_id → neg_risk_market_id."""
        result = {}
        for group_id, mids in neg_risk_groups.items():
            for mid in mids:
                result[mid] = group_id
        return result

    def calculate(self, period: str = '1M') -> Dict[str, Any]:
        period = (period or '1M').upper()
        if period not in self.PERIOD_WINDOWS:
            raise ValueError(f"Unsupported period '{period}'. Use ALL/1M/1W/1D.")

        from wallet_analysis.models import Wallet, Trade, Activity

        wallet = Wallet.objects.get(pk=self.wallet_id)
        trades = list(
            Trade.objects.filter(wallet=wallet)
            .select_related('market')
            .order_by('timestamp', 'id')
        )
        activities = list(
            Activity.objects.filter(wallet=wallet)
            .select_related('market')
            .order_by('timestamp', 'id')
        )

        # Build neg-risk group lookups
        neg_risk_groups = self._build_neg_risk_groups(wallet)
        parent_to_group = self._build_parent_to_group(neg_risk_groups, wallet)
        child_to_group = self._build_child_to_group(neg_risk_groups)

        events: List[Tuple[str, Any]] = [('trade', t) for t in trades]
        events.extend(('activity', a) for a in activities)
        events.sort(key=self._event_sort_key)

        period_start_ts = self._period_start_timestamp(period)
        cumulative_now = ZERO
        cumulative_at_period_start = ZERO if period == 'ALL' else None

        positions: Dict[str, AvgCostPositionState] = {}
        market_outcomes: Dict[int, set] = defaultdict(set)
        market_rows: Dict[Any, Dict[str, Any]] = defaultdict(
            lambda: {
                'trade_count': 0,
                'buys': ZERO,
                'sells': ZERO,
                'redeems': ZERO,
                'pnl': ZERO,
            }
        )
        daily_pnl = defaultdict(lambda: ZERO)

        total_buys = ZERO
        total_sells = ZERO
        total_redeems = ZERO
        total_rewards = ZERO

        for trade in trades:
            if trade.market_id:
                market_outcomes[trade.market_id].add((trade.outcome or '').strip())

        for event_type, obj in events:
            timestamp = obj.timestamp
            if cumulative_at_period_start is None and period_start_ts is not None and timestamp >= period_start_ts:
                cumulative_at_period_start = cumulative_now

            realized_delta = ZERO

            if event_type == 'trade':
                market_id = obj.market_id
                if not market_id:
                    continue

                outcome = (obj.outcome or '').strip()
                position_key = self._position_key(market_id, outcome)
                asset_id = (obj.asset or '').strip() or position_key
                price = self._coerce_decimal(obj.price)
                size = self._coerce_decimal(obj.size)
                if size <= ZERO:
                    continue

                pos = positions.get(position_key)
                if pos is None:
                    pos = AvgCostPositionState(
                        asset_id=asset_id,
                        market_id=market_id,
                        outcome=outcome,
                    )
                    positions[position_key] = pos

                pos.market_id = pos.market_id or market_id
                if outcome and not pos.outcome:
                    pos.outcome = outcome

                if obj.side == 'BUY':
                    old_cost = pos.avg_cost * pos.size
                    new_total_size = pos.size + size
                    if new_total_size > EPS:
                        pos.avg_cost = (old_cost + price * size) / new_total_size
                    pos.size = new_total_size
                    total_buys += price * size
                    if market_id:
                        market_rows[market_id]['trade_count'] += 1
                        market_rows[market_id]['buys'] += price * size

                elif obj.side == 'SELL':
                    qty = min(size, pos.size)
                    if qty > ZERO:
                        realized_delta = qty * (price - pos.avg_cost)
                        pos.realized_pnl += realized_delta
                        pos.size -= qty
                        if pos.size < EPS:
                            pos.size = ZERO
                            pos.avg_cost = ZERO
                        total_sells += price * qty
                        if market_id:
                            market_rows[market_id]['trade_count'] += 1
                            market_rows[market_id]['sells'] += price * qty
                            market_rows[market_id]['pnl'] += realized_delta

            else:
                activity_type = obj.activity_type
                market_id = obj.market_id
                if not market_id:
                    continue
                size = self._coerce_decimal(obj.size)
                usdc_value = self._coerce_decimal(obj.usdc_size)

                if activity_type == 'REWARD':
                    realized_delta = usdc_value
                    total_rewards += usdc_value

                elif activity_type == 'REDEEM':
                    market_positions = self._market_open_positions(positions, market_id)
                    if not market_positions:
                        # For neg-risk markets, conversion-created positions may use
                        # outcome='Yes' while the market_id is correct. Try again
                        # with a broader search.
                        yes_key = self._position_key(market_id, 'Yes')
                        if yes_key in positions and positions[yes_key].size > EPS:
                            market_positions = [positions[yes_key]]
                    if not market_positions:
                        continue

                    if usdc_value > ZERO:
                        # Match simulate_avg_cost.py:
                        # 1) Try exact-size match in same market.
                        # 2) Otherwise consume largest open positions first.
                        remaining = size
                        matched_realized = ZERO

                        exact = None
                        for market_pos in market_positions:
                            if abs(market_pos.size - size) < Decimal('0.5'):
                                exact = market_pos
                                break

                        if exact is not None:
                            qty = min(size, exact.size)
                            matched_realized += qty * (ONE - exact.avg_cost)
                            exact.realized_pnl += qty * (ONE - exact.avg_cost)
                            exact.size -= qty
                            if exact.size < EPS:
                                exact.size = ZERO
                                exact.avg_cost = ZERO
                            remaining = ZERO
                        else:
                            market_positions.sort(key=lambda p: p.size, reverse=True)
                            for market_pos in market_positions:
                                if remaining <= EPS:
                                    break
                                qty = min(remaining, market_pos.size)
                                if qty <= ZERO:
                                    continue
                                realized_piece = qty * (ONE - market_pos.avg_cost)
                                matched_realized += realized_piece
                                market_pos.realized_pnl += realized_piece
                                market_pos.size -= qty
                                if market_pos.size < EPS:
                                    market_pos.size = ZERO
                                    market_pos.avg_cost = ZERO
                                remaining -= qty

                        if matched_realized == ZERO:
                            continue

                        realized_delta = matched_realized
                        total_redeems += usdc_value
                        if market_id:
                            market_rows[market_id]['redeems'] += usdc_value
                            market_rows[market_id]['pnl'] += realized_delta
                    else:
                        # Loser redeem: zero-out all open positions in this market.
                        loser_realized = ZERO
                        for market_pos in market_positions:
                            if market_pos.size > EPS:
                                realized_piece = -(market_pos.size * market_pos.avg_cost)
                                loser_realized += realized_piece
                                market_pos.realized_pnl += realized_piece
                                market_pos.size = ZERO
                                market_pos.avg_cost = ZERO

                        if loser_realized == ZERO:
                            continue
                        realized_delta = loser_realized
                        if market_id:
                            market_rows[market_id]['pnl'] += realized_delta

                elif activity_type in ('SPLIT', 'CONVERSION', 'MERGE'):
                    if activity_type == 'SPLIT':
                        continue

                    if activity_type == 'CONVERSION':
                        # Neg-risk conversion: user bought "No" tokens in one child,
                        # then converted on the parent, distributing shares to siblings.
                        # The conversion itself is net-zero for PnL — the cost was the
                        # original BUY. We transfer the position from source child to
                        # all other children in the group.
                        group_id = parent_to_group.get(market_id)
                        if not group_id:
                            continue
                        group_children = [
                            mid for mid in neg_risk_groups.get(group_id, [])
                            if mid != market_id  # exclude the parent itself
                        ]
                        if not group_children:
                            continue

                        conv_size = size
                        conv_ts = timestamp

                        # Find the source BUY: a child position that was recently bought
                        # with ~same size and price ~$1 (neg-risk "No" tokens).
                        source_pos = None
                        source_key = None
                        best_match_diff = Decimal('999999')

                        for child_mid in group_children:
                            for pkey, pos in positions.items():
                                if pos.market_id != child_mid or pos.size < conv_size - ONE:
                                    continue
                                # Check if this position has enough shares and was bought at ~$1
                                if pos.avg_cost > Decimal('0.90'):
                                    size_diff = abs(pos.size - conv_size)
                                    if size_diff < best_match_diff:
                                        best_match_diff = size_diff
                                        source_pos = pos
                                        source_key = pkey

                        if source_pos is None:
                            # No matching source found — skip conversion
                            continue

                        # Transfer: deduct conv_size from source, create in siblings
                        transfer_qty = min(conv_size, source_pos.size)
                        transfer_cost = source_pos.avg_cost * transfer_qty
                        source_pos.size -= transfer_qty
                        if source_pos.size < EPS:
                            source_pos.size = ZERO
                            source_pos.avg_cost = ZERO

                        # Distribute to all OTHER children (not the source)
                        dest_children = [
                            mid for mid in group_children
                            if mid != source_pos.market_id
                        ]
                        if not dest_children:
                            continue

                        # Each destination child gets transfer_qty shares at
                        # cost_basis = transfer_cost / len(dest_children) per share.
                        # This means each child's shares cost $1/share effectively
                        # (since source was bought at ~$1).
                        cost_per_child = transfer_cost / len(dest_children)
                        cost_per_share = source_pos.avg_cost if source_pos.avg_cost > ZERO else ONE

                        for dest_mid in dest_children:
                            # Use a generic outcome since conversions have empty outcome
                            dest_key = self._position_key(dest_mid, 'Yes')
                            dest_pos = positions.get(dest_key)
                            if dest_pos is None:
                                dest_pos = AvgCostPositionState(
                                    asset_id=dest_key,
                                    market_id=dest_mid,
                                    outcome='Yes',
                                )
                                positions[dest_key] = dest_pos
                            # Update avg cost with new shares
                            old_total = dest_pos.avg_cost * dest_pos.size
                            dest_pos.size += transfer_qty
                            if dest_pos.size > EPS:
                                dest_pos.avg_cost = (old_total + cost_per_child) / dest_pos.size
                            dest_pos.market_id = dest_mid

                        # No realized PnL from conversion itself
                        continue

                    # Match simulate_avg_cost.py merge behavior even when split_mode='none':
                    # distribute merge proceeds per outcome and realize against open positions.
                    outcomes = market_outcomes.get(market_id, {'Yes', 'No'})
                    n_outcomes = len(outcomes)
                    rev_per_share = ZERO
                    if size > ZERO and n_outcomes > 0:
                        rev_per_share = usdc_value / (size * n_outcomes)

                    merge_realized = ZERO
                    for outcome in outcomes:
                        key = self._position_key(market_id, outcome)
                        pos = positions.get(key)
                        if pos is None or pos.size <= EPS:
                            continue

                        qty = min(size, pos.size)
                        if qty <= ZERO:
                            continue
                        realized_piece = qty * (rev_per_share - pos.avg_cost)
                        merge_realized += realized_piece
                        pos.realized_pnl += realized_piece
                        pos.size -= qty
                        if pos.size < EPS:
                            pos.size = ZERO
                            pos.avg_cost = ZERO

                    if merge_realized == ZERO:
                        continue
                    realized_delta = merge_realized
                    if market_id:
                        market_rows[market_id]['pnl'] += realized_delta

            if realized_delta != ZERO:
                cumulative_now += realized_delta
                if self._is_in_period(timestamp, period_start_ts):
                    event_date = obj.datetime.date().isoformat()
                    daily_pnl[event_date] += realized_delta

        if cumulative_at_period_start is None:
            # Period starts after the last event -> period PnL is 0.
            cumulative_at_period_start = cumulative_now

        period_pnl = cumulative_now if period == 'ALL' else (cumulative_now - cumulative_at_period_start)

        position_rows = []
        for pos in positions.values():
            if pos.size <= EPS and abs(pos.realized_pnl) <= EPS:
                continue
            position_rows.append({
                'asset': pos.asset_id,
                'market_id': pos.market_id,
                'outcome': pos.outcome,
                'size': float(pos.size),
                'avg_cost': float(pos.avg_cost),
                'realized_pnl': float(pos.realized_pnl),
            })

        position_rows.sort(key=lambda p: abs(p['realized_pnl']), reverse=True)

        return {
            'period': period,
            'total_pnl': float(cumulative_now),
            'period_pnl': float(period_pnl),
            'daily_pnl': self._format_daily_pnl(daily_pnl),
            'pnl_by_market': self._sorted_market_rows(market_rows),
            'positions': position_rows,
            'totals': {
                'total_buys': float(total_buys),
                'total_sells': float(total_sells),
                'total_redeems': float(total_redeems),
                'total_rewards': float(total_rewards),
            },
        }


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
    Cash flow P&L calculator.

    Formula: P&L = (sells + redeems + merges + rewards) - (buys + splits)
    Note: CONVERSIONs are token swaps, NOT cash inflows — excluded from PnL.

    This is the legacy method. The default is now CostBasisPnLCalculator.
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

        Loads data once and computes both full and filtered aggregations
        in a single pass to avoid redundant DB queries.
        """
        trades = self._provider.get_trades(wallet)
        activities = self._provider.get_activities(wallet)

        if not start_date and not end_date:
            # No filter — aggregate all data directly
            market_agg, daily_agg = self._aggregate(trades, activities)
            totals = market_agg.get_totals()
            return {
                'total_realized_pnl': float(totals.pnl),
                'daily_pnl': daily_agg.get_results()['daily_pnl'],
                'pnl_by_market': market_agg.get_results()['pnl_by_market'][:20],
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

        # Full aggregation on already-loaded data (no second DB hit)
        full_market_agg, _ = self._aggregate(trades, activities)
        full_pnl = float(full_market_agg.get_totals().pnl)

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
            'full_period_pnl': full_pnl,
        }


# Alias for clarity
CashFlowPnLCalculator = PnLCalculator


# Module-level convenience functions — use cost basis as default
_default_calculator = None
_default_cashflow_calculator = None


def _get_calculator():
    """Get or create the default cost basis calculator instance."""
    global _default_calculator
    if _default_calculator is None:
        from .cost_basis_calculator import CostBasisPnLCalculator
        _default_calculator = CostBasisPnLCalculator()
    return _default_calculator


def _get_cashflow_calculator() -> PnLCalculator:
    """Get or create the default cash flow calculator instance."""
    global _default_cashflow_calculator
    if _default_cashflow_calculator is None:
        _default_cashflow_calculator = PnLCalculator()
    return _default_cashflow_calculator


def calculate_wallet_pnl(wallet) -> Dict[str, Any]:
    """
    Calculate P&L for a wallet using cost basis method (default).

    Returns dict with total_realized_pnl, total_unrealized_pnl, total_pnl,
    cash_flow_pnl, daily_pnl, pnl_by_market, positions, and totals.
    """
    return _get_calculator().calculate(wallet)


def calculate_wallet_pnl_filtered(
    wallet,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> Dict[str, Any]:
    """Calculate P&L for a date range using cost basis method (default)."""
    return _get_calculator().calculate_filtered(wallet, start_date, end_date)


def calculate_wallet_pnl_cashflow(wallet) -> Dict[str, Any]:
    """Calculate P&L using the legacy cash flow method."""
    return _get_cashflow_calculator().calculate(wallet)
