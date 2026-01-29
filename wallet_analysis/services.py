"""
Database services for Polymarket wallet analysis.

Handles saving and querying data using Django ORM.
"""

import os
import django
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional

from django.utils import timezone

# Setup Django before importing models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
django.setup()

from django.db import transaction
from wallet_analysis.models import (
    Wallet, Market, Trade, Activity, Position,
    CurrentPosition, AnalysisRun, CopyTradingScenario
)
from src.api.models import Trade as TradeDTO


def safe_decimal(value, default=None) -> Optional[Decimal]:
    """Convert value to Decimal, handling infinity, NaN, and invalid values."""
    if value is None:
        return default
    try:
        f = float(value)
        if math.isinf(f) or math.isnan(f):
            return default
        return Decimal(str(f))
    except (ValueError, TypeError, InvalidOperation):
        return default


def timestamp_to_datetime(ts: int) -> datetime:
    """Convert Unix timestamp to timezone-aware datetime."""
    return timezone.make_aware(datetime.fromtimestamp(ts))


class DatabaseService:
    """
    Service for persisting analysis data to the database.

    Provides methods to save trades, activities, positions, and analysis results.
    """

    def get_or_create_wallet(self, address: str, name: str = "", pseudonym: str = "") -> Wallet:
        """Get or create a wallet record."""
        wallet, created = Wallet.objects.get_or_create(
            address=address.lower(),
            defaults={'name': name, 'pseudonym': pseudonym}
        )
        if not created and (name or pseudonym):
            if name:
                wallet.name = name
            if pseudonym:
                wallet.pseudonym = pseudonym
            wallet.save()
        return wallet

    def get_or_create_market(self, condition_id: str, title: str = "", **kwargs) -> Market:
        """Get or create a market record."""
        market, _ = Market.objects.update_or_create(
            condition_id=condition_id,
            defaults={'title': title, **kwargs}
        )
        return market

    def save_trades(self, wallet: Wallet, trades: List[TradeDTO], batch_size: int = 100) -> int:
        """
        Save trades to the database in batches to avoid locking.

        Returns the number of new trades inserted.
        """
        if not trades:
            return 0

        inserted = 0
        batch = []

        # Cache markets to reduce DB queries
        market_cache = {}

        for i, trade_dto in enumerate(trades):
            # Get or create market (cached)
            market = None
            if trade_dto.condition_id:
                if trade_dto.condition_id not in market_cache:
                    market, _ = Market.objects.get_or_create(
                        condition_id=trade_dto.condition_id,
                        defaults={'title': trade_dto.title or ''}
                    )
                    market_cache[trade_dto.condition_id] = market
                else:
                    market = market_cache[trade_dto.condition_id]

            try:
                side_value = trade_dto.side.value if hasattr(trade_dto.side, 'value') else str(trade_dto.side)

                batch.append(Trade(
                    wallet=wallet,
                    market=market,
                    transaction_hash=trade_dto.transaction_hash,
                    asset=trade_dto.asset or '',
                    timestamp=trade_dto.timestamp,
                    datetime=timestamp_to_datetime(trade_dto.timestamp),
                    side=side_value,
                    outcome=trade_dto.outcome or '',
                    price=Decimal(str(trade_dto.price)),
                    size=Decimal(str(trade_dto.size)),
                    total_value=Decimal(str(trade_dto.total_value)),
                ))
            except Exception:
                continue

            # Commit batch
            if len(batch) >= batch_size:
                try:
                    with transaction.atomic():
                        Trade.objects.bulk_create(batch, ignore_conflicts=True)
                    inserted += len(batch)
                except Exception as e:
                    # On conflict, fall back to individual inserts
                    for trade in batch:
                        try:
                            trade.save()
                            inserted += 1
                        except Exception:
                            pass
                batch = []

        # Final batch
        if batch:
            try:
                with transaction.atomic():
                    Trade.objects.bulk_create(batch, ignore_conflicts=True)
                inserted += len(batch)
            except Exception:
                for trade in batch:
                    try:
                        trade.save()
                        inserted += 1
                    except Exception:
                        pass

        return inserted

    def save_activities(
        self,
        wallet: Wallet,
        activity_data: Dict[str, List[dict]],
        batch_size: int = 100
    ) -> Dict[str, int]:
        """
        Save activity data (REDEEM, SPLIT, MERGE, REWARD) to database in batches.

        Returns dict with count of inserted items per type.
        """
        counts = {}
        market_cache = {}

        for activity_type, items in activity_data.items():
            if activity_type == 'TRADE':
                continue

            batch = []
            inserted = 0

            for item in items:
                try:
                    # Get or create market if condition_id exists (cached)
                    market = None
                    condition_id = item.get('conditionId')
                    if condition_id:
                        if condition_id not in market_cache:
                            market, _ = Market.objects.get_or_create(
                                condition_id=condition_id,
                                defaults={'title': item.get('title', '')}
                            )
                            market_cache[condition_id] = market
                        else:
                            market = market_cache[condition_id]

                    ts = item.get('timestamp', 0)
                    batch.append(Activity(
                        wallet=wallet,
                        market=market,
                        activity_type=activity_type,
                        transaction_hash=item.get('transactionHash', ''),
                        timestamp=ts,
                        datetime=timestamp_to_datetime(ts) if ts else timezone.now(),
                        size=Decimal(str(item.get('size', 0))),
                        usdc_size=Decimal(str(item.get('usdcSize', 0))),
                        title=item.get('title', ''),
                    ))

                    # Commit batch
                    if len(batch) >= batch_size:
                        try:
                            with transaction.atomic():
                                Activity.objects.bulk_create(batch, ignore_conflicts=True)
                            inserted += len(batch)
                        except Exception:
                            pass
                        batch = []

                except Exception:
                    continue

            # Final batch
            if batch:
                try:
                    with transaction.atomic():
                        Activity.objects.bulk_create(batch, ignore_conflicts=True)
                    inserted += len(batch)
                except Exception:
                    pass

            counts[activity_type] = inserted

        return counts

    @transaction.atomic
    def save_positions_from_subgraph(
        self,
        wallet: Wallet,
        positions: List[dict]
    ) -> int:
        """Save position data from PnL subgraph."""
        if not positions:
            return 0

        # Clear existing positions for this wallet
        Position.objects.filter(wallet=wallet).delete()

        inserted = 0
        for pos in positions:
            try:
                Position.objects.create(
                    wallet=wallet,
                    token_id=pos.get('tokenId', ''),
                    amount=Decimal(str(float(pos.get('amount', 0)) / 1e6)),
                    avg_price=Decimal(str(float(pos.get('avgPrice', 0)) / 1e6)),
                    realized_pnl=Decimal(str(float(pos.get('realizedPnl', 0)) / 1e6)),
                    total_bought=Decimal(str(float(pos.get('totalBought', 0)) / 1e6)),
                )
                inserted += 1
            except Exception:
                continue

        return inserted

    @transaction.atomic
    def save_current_positions(
        self,
        wallet: Wallet,
        positions: List[dict]
    ) -> int:
        """Save current positions from /positions endpoint."""
        if not positions:
            return 0

        # Clear existing current positions for this wallet
        CurrentPosition.objects.filter(wallet=wallet).delete()

        inserted = 0
        for pos in positions:
            try:
                # Get or create market
                market = None
                condition_id = pos.get('conditionId')
                if condition_id:
                    market, _ = Market.objects.get_or_create(
                        condition_id=condition_id,
                        defaults={'title': pos.get('title', '')}
                    )

                CurrentPosition.objects.create(
                    wallet=wallet,
                    market=market,
                    asset=pos.get('asset', ''),
                    outcome=pos.get('outcome', ''),
                    size=Decimal(str(pos.get('size', 0))),
                    avg_price=Decimal(str(pos.get('avgPrice', 0))),
                    initial_value=Decimal(str(pos.get('initialValue', 0))),
                    current_value=Decimal(str(pos.get('currentValue', 0))),
                    cash_pnl=Decimal(str(pos.get('cashPnl', 0))),
                    percent_pnl=Decimal(str(pos.get('percentPnl', 0))),
                    realized_pnl=Decimal(str(pos.get('realizedPnl', 0))),
                    cur_price=Decimal(str(pos.get('curPrice', 0))),
                    redeemable=pos.get('redeemable', False),
                    end_date=pos.get('endDate') or None,
                )
                inserted += 1
            except Exception:
                continue

        return inserted

    @transaction.atomic
    def save_analysis_run(
        self,
        wallet: Wallet,
        summary: Dict[str, Any],
        cash_flow: Dict[str, Any],
        performance: Dict[str, Any],
        period_start_hours: int,
        period_end_hours: int,
    ) -> AnalysisRun:
        """Save an analysis run with all its metrics."""
        analysis_run = AnalysisRun.objects.create(
            wallet=wallet,
            period_start_hours_ago=period_start_hours,
            period_end_hours_ago=period_end_hours,
            # Trade summary
            total_trades=summary.get('total_trades', 0),
            total_buys=summary.get('total_buys', 0),
            total_sells=summary.get('total_sells', 0),
            total_volume_usd=Decimal(str(summary.get('total_volume_usd', 0))),
            unique_markets=summary.get('unique_markets', 0),
            # Cash flow
            buy_cost=Decimal(str(cash_flow.get('buy_cost', 0))),
            sell_revenue=Decimal(str(cash_flow.get('sell_revenue', 0))),
            redeem_revenue=Decimal(str(cash_flow.get('redeem_revenue', 0))),
            split_cost=Decimal(str(cash_flow.get('split_cost', 0))),
            merge_revenue=Decimal(str(cash_flow.get('merge_revenue', 0))),
            reward_revenue=Decimal(str(cash_flow.get('reward_revenue', 0))),
            cash_flow_pnl=Decimal(str(cash_flow.get('total_pnl', 0))),
            # Subgraph P&L
            subgraph_realized_pnl=safe_decimal(cash_flow.get('subgraph_realized_pnl')),
            subgraph_total_bought=safe_decimal(cash_flow.get('subgraph_total_bought')),
            subgraph_total_positions=cash_flow.get('subgraph_total_positions'),
            # Performance (use safe_decimal to handle infinity/nan)
            win_rate_percent=safe_decimal(performance.get('win_rate_percent')),
            profit_factor=safe_decimal(performance.get('profit_factor')),
            max_drawdown_usd=safe_decimal(performance.get('max_drawdown_usd')),
        )

        # Update wallet with latest P&L
        if cash_flow.get('subgraph_realized_pnl'):
            wallet.subgraph_realized_pnl = Decimal(str(cash_flow['subgraph_realized_pnl']))
            wallet.subgraph_total_bought = Decimal(str(cash_flow.get('subgraph_total_bought', 0)))
            wallet.subgraph_total_positions = cash_flow.get('subgraph_total_positions')
            wallet.save()

        return analysis_run

    @transaction.atomic
    def save_copy_trading_scenarios(
        self,
        analysis_run: AnalysisRun,
        scenarios: List[Dict[str, Any]]
    ) -> int:
        """Save copy trading simulation scenarios."""
        if not scenarios:
            return 0

        inserted = 0
        for scenario in scenarios:
            try:
                CopyTradingScenario.objects.create(
                    analysis_run=analysis_run,
                    slippage_value=Decimal(str(scenario.get('slippage_value', 0))),
                    slippage_mode=scenario.get('slippage_mode', 'percentage'),
                    total_trades_copied=scenario.get('total_trades_copied', 0),
                    total_volume_usd=Decimal(str(scenario.get('total_volume_usd', 0))),
                    original_pnl_usd=Decimal(str(scenario.get('original_pnl_usd', 0))),
                    estimated_copy_pnl_usd=Decimal(str(scenario.get('estimated_copy_pnl_usd', 0))),
                    pnl_difference_usd=Decimal(str(scenario.get('pnl_difference_usd', 0))),
                    pnl_difference_percent=Decimal(str(scenario.get('pnl_difference_percent', 0))),
                    profitable=scenario.get('profitable', False),
                )
                inserted += 1
            except Exception:
                continue

        return inserted

    def save_market_resolutions(self, resolutions: Dict[str, dict]) -> int:
        """Save market resolution data."""
        if not resolutions:
            return 0

        updated = 0
        for condition_id, resolution in resolutions.items():
            try:
                Market.objects.update_or_create(
                    condition_id=condition_id,
                    defaults={
                        'resolved': resolution.get('resolved', False),
                        'winning_outcome': resolution.get('winning_outcome', ''),
                        'resolution_timestamp': resolution.get('resolution_timestamp'),
                    }
                )
                updated += 1
            except Exception:
                continue

        return updated

    # Query methods

    def get_wallet_trades(
        self,
        wallet_address: str,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
        side: Optional[str] = None,
    ) -> List[Trade]:
        """Query trades for a wallet with optional filters."""
        queryset = Trade.objects.filter(wallet__address=wallet_address.lower())

        if start_timestamp:
            queryset = queryset.filter(timestamp__gte=start_timestamp)
        if end_timestamp:
            queryset = queryset.filter(timestamp__lte=end_timestamp)
        if side:
            queryset = queryset.filter(side=side)

        return list(queryset.select_related('market'))

    def get_wallet_pnl_by_market(self, wallet_address: str) -> List[dict]:
        """Get P&L breakdown by market for a wallet."""
        from django.db.models import Sum, Count, Case, When, F

        trades = Trade.objects.filter(wallet__address=wallet_address.lower())

        return list(trades.values('market__title', 'market__condition_id').annotate(
            trade_count=Count('id'),
            buy_volume=Sum(Case(
                When(side='BUY', then=F('total_value')),
                default=0,
            )),
            sell_volume=Sum(Case(
                When(side='SELL', then=F('total_value')),
                default=0,
            )),
        ).order_by('-trade_count'))

    def get_wallet_daily_volume(self, wallet_address: str) -> List[dict]:
        """Get daily trading volume for a wallet."""
        from django.db.models import Sum, Count
        from django.db.models.functions import TruncDate

        trades = Trade.objects.filter(wallet__address=wallet_address.lower())

        return list(trades.annotate(
            date=TruncDate('datetime')
        ).values('date').annotate(
            trade_count=Count('id'),
            volume=Sum('total_value'),
        ).order_by('-date'))

    def get_wallet_activity_summary(self, wallet_address: str) -> Dict[str, dict]:
        """Get summary of all activity types for a wallet."""
        from django.db.models import Sum, Count

        activities = Activity.objects.filter(wallet__address=wallet_address.lower())

        result = {}
        for row in activities.values('activity_type').annotate(
            count=Count('id'),
            total_usdc=Sum('usdc_size'),
        ):
            result[row['activity_type']] = {
                'count': row['count'],
                'total_usdc': float(row['total_usdc'] or 0),
            }

        return result

    def get_analysis_history(self, wallet_address: str, limit: int = 10) -> List[AnalysisRun]:
        """Get analysis run history for a wallet."""
        return list(
            AnalysisRun.objects
            .filter(wallet__address=wallet_address.lower())
            .prefetch_related('copy_scenarios')
            .order_by('-timestamp')[:limit]
        )
