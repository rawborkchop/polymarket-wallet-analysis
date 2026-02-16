"""
Database services for Polymarket wallet analysis.

Handles saving and querying data using Django ORM.
"""

import os
import django
import math
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

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

    def save_trades(self, wallet: Wallet, trades: List[TradeDTO], batch_size: int = 1000) -> int:
        """
        Save trades to the database in batches to avoid locking.

        Returns the number of new trades inserted.
        """
        if not trades:
            return 0

        inserted = 0
        batch = []

        # Preload markets for this payload to minimize per-row lookups.
        condition_ids = {t.condition_id for t in trades if getattr(t, 'condition_id', None)}
        market_cache = {m.condition_id: m for m in Market.objects.filter(condition_id__in=condition_ids)}

        for trade_dto in trades:
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
            except Exception as e:
                logger.warning(
                    f"Skipped invalid trade for wallet {wallet.address}: "
                    f"tx={getattr(trade_dto, 'transaction_hash', 'unknown')}, error={e}"
                )
                continue

            # Commit batch
            if len(batch) >= batch_size:
                try:
                    with transaction.atomic():
                        created = Trade.objects.bulk_create(batch, ignore_conflicts=True)
                    inserted += len(created)
                except Exception as e:
                    logger.warning(f"Bulk insert failed for {len(batch)} trades, trying individual: {e}")
                    for trade in batch:
                        try:
                            trade.save()
                            inserted += 1
                        except Exception as individual_error:
                            logger.debug(f"Individual trade insert failed: {individual_error}")
                batch = []

        # Final batch
        if batch:
            try:
                with transaction.atomic():
                    created = Trade.objects.bulk_create(batch, ignore_conflicts=True)
                inserted += len(created)
            except Exception as e:
                logger.warning(f"Final bulk insert failed for {len(batch)} trades: {e}")
                for trade in batch:
                    try:
                        trade.save()
                        inserted += 1
                    except Exception as individual_error:
                        logger.debug(f"Individual trade insert failed: {individual_error}")

        logger.info(f"Saved {inserted} trades for wallet {wallet.address} (from {len(trades)} provided)")
        return inserted

    def save_activities(
        self,
        wallet: Wallet,
        activity_data: Dict[str, List[dict]],
        batch_size: int = 1000
    ) -> Dict[str, int]:
        """
        Save activity data (REDEEM, SPLIT, MERGE, REWARD) to database in batches.

        Returns dict with count of inserted items per type.
        """
        counts = {}

        payload_condition_ids = set()
        for items in activity_data.values():
            if not isinstance(items, list):
                continue
            for item in items:
                condition_id = item.get('conditionId')
                if condition_id:
                    payload_condition_ids.add(condition_id)
        market_cache = {m.condition_id: m for m in Market.objects.filter(condition_id__in=payload_condition_ids)}

        for activity_type, items in activity_data.items():
            # Skip non-persisted keys (trade rows are stored in Trade table, and
            # metadata keys such as _errors are not activity payloads).
            if activity_type == 'TRADE' or activity_type.startswith('_'):
                continue
            if not isinstance(items, list):
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
                        asset=item.get('asset', ''),
                        outcome=item.get('outcome', ''),
                        title=item.get('title', ''),
                    ))

                    # Commit batch
                    if len(batch) >= batch_size:
                        try:
                            with transaction.atomic():
                                created = Activity.objects.bulk_create(batch, ignore_conflicts=True)
                            inserted += len(created)
                        except Exception as e:
                            logger.warning(f"Bulk insert failed for {activity_type} activities: {e}")
                        batch = []

                except Exception as e:
                    logger.warning(
                        f"Skipped invalid {activity_type} activity for wallet {wallet.address}: "
                        f"tx={item.get('transactionHash', 'unknown')}, error={e}"
                    )
                    continue

            # Final batch
            if batch:
                try:
                    with transaction.atomic():
                        created = Activity.objects.bulk_create(batch, ignore_conflicts=True)
                    inserted += len(created)
                except Exception as e:
                    logger.warning(f"Final bulk insert failed for {activity_type} activities: {e}")

            counts[activity_type] = inserted
            if inserted > 0:
                logger.info(f"Saved {inserted} {activity_type} activities for wallet {wallet.address}")

        total_saved = sum(counts.values())
        total_provided = sum(len(items) for k, items in activity_data.items() if k != 'TRADE')
        logger.info(f"Activity save complete for {wallet.address}: {total_saved}/{total_provided} saved")

        # Backfill: update existing activities that have empty asset/outcome
        # with data from the incoming payload (re-fetched from API).
        backfilled = self._backfill_activity_fields(wallet, activity_data, market_cache)
        if backfilled > 0:
            logger.info(f"Backfilled asset/outcome on {backfilled} activities for {wallet.address}")

        return counts

    def _backfill_activity_fields(
        self,
        wallet: Wallet,
        activity_data: Dict[str, List[dict]],
        market_cache: Dict[str, Market],
    ) -> int:
        """
        Update existing activities that have empty asset/outcome fields.

        When activities are first fetched, they may lack asset/outcome data.
        On subsequent fetches the API may provide this data. Since bulk_create
        with ignore_conflicts=True won't update existing rows, we do a
        targeted update here.
        """
        # Collect incoming items that have asset or outcome data
        backfill_candidates = []
        for activity_type, items in activity_data.items():
            if activity_type == 'TRADE' or activity_type.startswith('_'):
                continue
            if not isinstance(items, list):
                continue
            for item in items:
                asset = item.get('asset', '')
                outcome = item.get('outcome', '')
                if not asset and not outcome:
                    continue
                backfill_candidates.append({
                    'activity_type': activity_type,
                    'transaction_hash': item.get('transactionHash', ''),
                    'timestamp': item.get('timestamp', 0),
                    'asset': asset,
                    'outcome': outcome,
                })

        if not backfill_candidates:
            return 0

        # Find existing activities for this wallet that have empty asset/outcome
        empty_activities = Activity.objects.filter(
            wallet=wallet,
            asset='',
        ).values_list('id', 'transaction_hash', 'activity_type', 'timestamp')

        # Build lookup by (tx_hash, activity_type, timestamp)
        empty_lookup = {}
        for pk, tx_hash, act_type, ts in empty_activities:
            empty_lookup[(tx_hash, act_type, ts)] = pk

        # Match candidates to existing records
        to_update = []
        for candidate in backfill_candidates:
            key = (
                candidate['transaction_hash'],
                candidate['activity_type'],
                candidate['timestamp'],
            )
            pk = empty_lookup.get(key)
            if pk is not None:
                activity = Activity(pk=pk, asset=candidate['asset'], outcome=candidate['outcome'])
                # We need to set all fields for bulk_update, so fetch the full object
                to_update.append((pk, candidate['asset'], candidate['outcome']))

        if not to_update:
            return 0

        # Bulk update in batches
        updated = 0
        batch_size = 100
        for i in range(0, len(to_update), batch_size):
            batch = to_update[i:i + batch_size]
            pks = [pk for pk, _, _ in batch]
            activities = {a.pk: a for a in Activity.objects.filter(pk__in=pks)}
            update_objs = []
            for pk, asset, outcome in batch:
                if pk in activities:
                    act = activities[pk]
                    act.asset = asset
                    act.outcome = outcome
                    update_objs.append(act)
            if update_objs:
                Activity.objects.bulk_update(update_objs, ['asset', 'outcome'])
                updated += len(update_objs)

        return updated

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

        objects = []
        for pos in positions:
            try:
                objects.append(Position(
                    wallet=wallet,
                    token_id=pos.get('tokenId', ''),
                    amount=Decimal(str(float(pos.get('amount', 0)) / 1e6)),
                    avg_price=Decimal(str(float(pos.get('avgPrice', 0)) / 1e6)),
                    realized_pnl=Decimal(str(float(pos.get('realizedPnl', 0)) / 1e6)),
                    total_bought=Decimal(str(float(pos.get('totalBought', 0)) / 1e6)),
                ))
            except Exception:
                continue

        if objects:
            Position.objects.bulk_create(objects)
        return len(objects)

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

        market_cache = {}
        objects = []
        for pos in positions:
            try:
                # Get or create market (cached)
                market = None
                condition_id = pos.get('conditionId')
                if condition_id:
                    if condition_id not in market_cache:
                        market, _ = Market.objects.get_or_create(
                            condition_id=condition_id,
                            defaults={'title': pos.get('title', '')}
                        )
                        market_cache[condition_id] = market
                    else:
                        market = market_cache[condition_id]

                objects.append(CurrentPosition(
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
                ))
            except Exception:
                continue

        if objects:
            CurrentPosition.objects.bulk_create(objects)
        return len(objects)

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
            # preview_pnl is from trade_service (fetch-time estimate)
            # The authoritative P&L is calculated by pnl_calculator from DB
            cash_flow_pnl=Decimal(str(cash_flow.get('preview_pnl', cash_flow.get('total_pnl', 0)))),
            # Performance (use safe_decimal to handle infinity/nan)
            win_rate_percent=safe_decimal(performance.get('win_rate_percent')),
            profit_factor=safe_decimal(performance.get('profit_factor')),
            max_drawdown_usd=safe_decimal(performance.get('max_drawdown_usd')),
        )

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

        condition_ids = list(resolutions.keys())
        existing = {m.condition_id: m for m in Market.objects.filter(condition_id__in=condition_ids)}

        to_update = []
        to_create = []

        for condition_id, resolution in resolutions.items():
            resolved = resolution.get('resolved', False)
            winning_outcome = resolution.get('winning_outcome') or ''
            resolution_timestamp = resolution.get('resolution_timestamp')

            if condition_id in existing:
                market = existing[condition_id]
                market.resolved = resolved
                market.winning_outcome = winning_outcome
                market.resolution_timestamp = resolution_timestamp
                to_update.append(market)
            else:
                to_create.append(Market(
                    condition_id=condition_id,
                    title='',
                    resolved=resolved,
                    winning_outcome=winning_outcome,
                    resolution_timestamp=resolution_timestamp,
                ))

        if to_update:
            Market.objects.bulk_update(to_update, ['resolved', 'winning_outcome', 'resolution_timestamp'])
        if to_create:
            Market.objects.bulk_create(to_create, ignore_conflicts=True)

        return len(to_update) + len(to_create)

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
