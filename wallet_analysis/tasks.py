"""
Celery tasks for wallet data fetching.

These tasks run in separate worker processes, allowing the main
Django server to remain responsive while fetching wallet data.
"""

from celery import shared_task
from celery.utils.log import get_task_logger
from datetime import datetime, time, timedelta

logger = get_task_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def fetch_wallet_data(self, wallet_id: int, start_date: str = None, end_date: str = None):
    """
    Fetch and save wallet data from Polymarket APIs.

    Args:
        wallet_id: Database ID of the wallet
        start_date: Optional start date (YYYY-MM-DD)
        end_date: Optional end date (YYYY-MM-DD)
    """
    from wallet_analysis.models import Wallet
    from wallet_analysis.services import DatabaseService
    from src.api.polymarket_client import PolymarketClient
    from src.services.trade_service import TradeService
    from src.services.analytics_service import AnalyticsService
    from src.services.copy_trading_analyzer import CopyTradingAnalyzer

    try:
        wallet = Wallet.objects.get(pk=wallet_id)
    except Wallet.DoesNotExist:
        logger.error(f"Wallet {wallet_id} not found")
        return {'status': 'error', 'message': 'Wallet not found'}

    address = wallet.address
    logger.info(f"Starting data fetch for wallet {address}")

    # Update task state
    self.update_state(state='PROGRESS', meta={
        'wallet_id': wallet_id,
        'address': address,
        'stage': 'initializing',
        'progress': 0
    })

    try:
        db_service = DatabaseService()
        client = PolymarketClient()
        trade_service = TradeService(client)
        analytics_service = AnalyticsService()
        copy_trading_analyzer = CopyTradingAnalyzer(use_percentage=False)

        # Calculate time range
        now = datetime.now()
        if end_date:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            end_dt = datetime.combine(end_dt.date(), time.max)
            before_timestamp = int(end_dt.timestamp())
            end_date_obj = end_dt.date()
        else:
            before_timestamp = int(now.timestamp())
            end_date_obj = now.date()

        if start_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            after_timestamp = int(start_dt.timestamp())
            start_date_obj = start_dt.date()
        else:
            after_timestamp = int(now.timestamp() - (30 * 24 * 60 * 60))  # 30 days
            start_date_obj = (now - timedelta(days=30)).date()

        # Stage 1: Fetch activity data
        self.update_state(state='PROGRESS', meta={
            'wallet_id': wallet_id,
            'address': address,
            'stage': 'fetching_activity',
            'progress': 10
        })

        activity_result = trade_service.get_all_activity(address, after_timestamp, before_timestamp)
        trades = activity_result.get("trades", [])
        raw_activity = activity_result.get("raw_activity", {})
        cash_flow = activity_result.get("cash_flow", {})

        logger.info(f"Fetched {len(trades)} trades for {address}")

        # Stage 2: Save trades
        self.update_state(state='PROGRESS', meta={
            'wallet_id': wallet_id,
            'address': address,
            'stage': 'saving_trades',
            'progress': 30,
            'trades_count': len(trades)
        })

        if trades:
            db_service.save_trades(wallet, trades)
            db_service.save_activities(wallet, raw_activity)

        # Stage 3: Update wallet date range
        self.update_state(state='PROGRESS', meta={
            'wallet_id': wallet_id,
            'address': address,
            'stage': 'updating_wallet',
            'progress': 70
        })

        # Update date range (expand, don't replace)
        if wallet.data_start_date is None or start_date_obj < wallet.data_start_date:
            wallet.data_start_date = start_date_obj
        if wallet.data_end_date is None or end_date_obj > wallet.data_end_date:
            wallet.data_end_date = end_date_obj

        wallet.save()

        # Calculate P&L using the single source of truth (pnl_calculator)
        # This is done AFTER saving trades so pnl_calculator has all data
        from wallet_analysis.pnl_calculator import calculate_wallet_pnl
        pnl_result = calculate_wallet_pnl(wallet)
        wallet.subgraph_realized_pnl = pnl_result['total_realized_pnl']
        wallet.subgraph_total_bought = pnl_result['totals'].get('total_buys', 0) + pnl_result['totals'].get('total_splits', 0)
        wallet.save(update_fields=['subgraph_realized_pnl', 'subgraph_total_bought'])

        # Stage 4: Run analytics
        self.update_state(state='PROGRESS', meta={
            'wallet_id': wallet_id,
            'address': address,
            'stage': 'running_analytics',
            'progress': 90
        })

        if trades:
            analytics = analytics_service.analyze(trades)
            resolutions = analytics.pop("_resolutions", {})
            copy_analysis = copy_trading_analyzer.analyze(trades, resolutions, cash_flow)

            db_service.save_market_resolutions(resolutions)
            period_hours = int((before_timestamp - after_timestamp) / 3600)
            analysis_run = db_service.save_analysis_run(
                wallet=wallet,
                summary=analytics.get("summary", {}),
                cash_flow=cash_flow,
                performance=analytics.get("performance", {}),
                period_start_hours=period_hours,
                period_end_hours=0,
            )
            db_service.save_copy_trading_scenarios(analysis_run, copy_analysis.get("scenarios", []))

        logger.info(f"Completed data fetch for wallet {address}")

        return {
            'status': 'success',
            'wallet_id': wallet_id,
            'address': address,
            'trades_count': len(trades),
            'realized_pnl': float(wallet.subgraph_realized_pnl or 0),  # From pnl_calculator
        }

    except Exception as e:
        logger.error(f"Error fetching wallet {address}: {e}")
        # Retry on failure
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            return {
                'status': 'error',
                'wallet_id': wallet_id,
                'message': str(e)
            }


@shared_task(bind=True)
def extend_wallet_range_task(self, wallet_id: int, direction: str, days: int = 30):
    """
    Extend the date range for a wallet.

    Args:
        wallet_id: Database ID of the wallet
        direction: 'backward' or 'forward'
        days: Number of days to extend
    """
    from wallet_analysis.models import Wallet

    try:
        wallet = Wallet.objects.get(pk=wallet_id)
    except Wallet.DoesNotExist:
        return {'status': 'error', 'message': 'Wallet not found'}

    if direction == 'backward':
        current_start = wallet.data_start_date or datetime.now().date()
        end_date = current_start - timedelta(days=1)
        start_date = end_date - timedelta(days=days)
    elif direction == 'forward':
        current_end = wallet.data_end_date or datetime.now().date()
        start_date = current_end + timedelta(days=1)
        end_date = min(start_date + timedelta(days=days), datetime.now().date())
    else:
        return {'status': 'error', 'message': 'Invalid direction'}

    # Call the main fetch task
    return fetch_wallet_data.delay(
        wallet_id,
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d')
    )


@shared_task
def cleanup_old_analyses(days: int = 30):
    """Remove analysis runs older than specified days."""
    from wallet_analysis.models import AnalysisRun
    from django.utils import timezone

    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = AnalysisRun.objects.filter(timestamp__lt=cutoff).delete()
    logger.info(f"Deleted {deleted} old analysis runs")
    return {'deleted': deleted}
