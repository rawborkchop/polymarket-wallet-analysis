"""Django REST Framework views for wallet analysis API."""

from django.db.models import Sum, Count, Q, Min, Max
from django.db.models.functions import TruncDate
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Wallet, Market, Trade, Activity,
    AnalysisRun, CopyTradingScenario
)
from .serializers import (
    WalletSerializer, WalletSummarySerializer, MarketSerializer,
    TradeSerializer, ActivitySerializer, AnalysisRunSerializer,
    AnalysisRunSummarySerializer, WalletStatsSerializer, DashboardStatsSerializer
)


class WalletViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoints for wallets.

    list: GET /api/wallets/
    retrieve: GET /api/wallets/{id}/
    """
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer

    def get_serializer_class(self):
        if self.action == 'list':
            return WalletSummarySerializer
        return WalletSerializer

    @action(detail=True, methods=['get'])
    def trades(self, request, pk=None):
        """GET /api/wallets/{id}/trades/ - Get wallet's trades."""
        wallet = self.get_object()
        trades = wallet.trades.all()[:100]
        serializer = TradeSerializer(trades, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def activities(self, request, pk=None):
        """GET /api/wallets/{id}/activities/ - Get wallet's activities."""
        wallet = self.get_object()
        activities = wallet.activities.all()[:100]
        serializer = ActivitySerializer(activities, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def analyses(self, request, pk=None):
        """GET /api/wallets/{id}/analyses/ - Get wallet's analysis history."""
        wallet = self.get_object()
        analyses = wallet.analysis_runs.all()[:20]
        serializer = AnalysisRunSerializer(analyses, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        """GET /api/wallets/{id}/stats/ - Get wallet statistics."""
        from datetime import datetime

        wallet = self.get_object()

        # Parse optional date range filters for charts
        chart_start = request.query_params.get('chart_start')
        chart_end = request.query_params.get('chart_end')

        # Parse date filters BEFORE calculating anything
        start_date_obj = None
        end_date_obj = None
        if chart_start:
            try:
                start_date_obj = datetime.strptime(chart_start, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid chart_start format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        if chart_end:
            try:
                end_date_obj = datetime.strptime(chart_end, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Invalid chart_end format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        period = (request.query_params.get('period') or '1M').upper()
        valid_periods = {'ALL', '1M', '1W', '1D'}
        if period not in valid_periods:
            return Response(
                {'error': 'Invalid period. Use one of: ALL, 1M, 1W, 1D'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Trade stats (filtered by date range if specified)
        trades = wallet.trades.all()
        if start_date_obj:
            trades = trades.filter(datetime__date__gte=start_date_obj)
        if end_date_obj:
            trades = trades.filter(datetime__date__lte=end_date_obj)

        trade_stats = trades.aggregate(
            total_trades=Count('id'),
            total_buys=Count('id', filter=Q(side='BUY')),
            total_sells=Count('id', filter=Q(side='SELL')),
            total_volume=Sum('size'),
        )

        # Unique markets (also filtered)
        unique_markets = trades.order_by().values('market_id').distinct().count()

        # Activity by type (filtered by date range if specified)
        activities = wallet.activities.all()
        if start_date_obj:
            activities = activities.filter(datetime__date__gte=start_date_obj)
        if end_date_obj:
            activities = activities.filter(datetime__date__lte=end_date_obj)

        activity_by_type = {
            a['activity_type']: {'count': a['count'], 'total_usdc': float(a['total_usdc'] or 0)}
            for a in activities.values('activity_type').annotate(
                count=Count('id'),
                total_usdc=Sum('usdc_size')
            )
        }

        # Avg cost basis P&L is read from cached AnalysisRun payload.
        # Replay is never done on the normal request path.
        from datetime import timedelta
        from django.db.models import Max
        from django.utils import timezone
        from .calculators.pnl_calculator import AvgCostBasisCalculator

        latest_analysis_for_cache = wallet.analysis_runs.prefetch_related('copy_scenarios').first()
        cache_payload = latest_analysis_for_cache.avg_cost_cache if latest_analysis_for_cache else None

        trade_fingerprint = wallet.trades.aggregate(count=Count('id'), max_id=Max('id'))
        activity_fingerprint = wallet.activities.aggregate(count=Count('id'), max_id=Max('id'))
        trade_count = trade_fingerprint['count'] or 0
        activity_count = activity_fingerprint['count'] or 0
        max_trade_id = trade_fingerprint['max_id']
        max_activity_id = activity_fingerprint['max_id']

        ttl_cutoff = timezone.now() - timedelta(minutes=5)
        period_cache = cache_payload.get(period) if isinstance(cache_payload, dict) else None
        cache_valid = (
            latest_analysis_for_cache is not None
            and period_cache is not None
            and latest_analysis_for_cache.avg_cost_cache_trade_count == trade_count
            and latest_analysis_for_cache.avg_cost_cache_activity_count == activity_count
            and latest_analysis_for_cache.avg_cost_cache_max_trade_id == max_trade_id
            and latest_analysis_for_cache.avg_cost_cache_max_activity_id == max_activity_id
            and latest_analysis_for_cache.avg_cost_cache_updated_at is not None
            and latest_analysis_for_cache.avg_cost_cache_updated_at >= ttl_cutoff
        )

        if cache_valid:
            pnl_result = period_cache
        elif isinstance(cache_payload, dict) and cache_payload and period in cache_payload:
            # Cache exists for this specific period (stale but usable).
            pnl_result = cache_payload[period]
        else:
            # One-time bootstrap when no cache exists yet.
            pnl_result = AvgCostBasisCalculator(wallet.id).calculate(period=period)
            if latest_analysis_for_cache is None:
                latest_analysis_for_cache = AnalysisRun.objects.create(
                    wallet=wallet,
                    period_start_hours_ago=0,
                    period_end_hours_ago=0,
                    total_trades=trade_count,
                )
                cache_payload = {}
            elif not isinstance(cache_payload, dict):
                cache_payload = {}

            cache_payload[period] = pnl_result
            latest_analysis_for_cache.avg_cost_cache = cache_payload
            latest_analysis_for_cache.avg_cost_cache_trade_count = trade_count
            latest_analysis_for_cache.avg_cost_cache_activity_count = activity_count
            latest_analysis_for_cache.avg_cost_cache_max_trade_id = max_trade_id
            latest_analysis_for_cache.avg_cost_cache_max_activity_id = max_activity_id
            latest_analysis_for_cache.avg_cost_cache_updated_at = timezone.now()
            latest_analysis_for_cache.save(
                update_fields=[
                    'avg_cost_cache',
                    'avg_cost_cache_trade_count',
                    'avg_cost_cache_activity_count',
                    'avg_cost_cache_max_trade_id',
                    'avg_cost_cache_max_activity_id',
                    'avg_cost_cache_updated_at',
                ]
            )

        # Daily P&L already comes filtered from the calculator
        daily_pnl_data = pnl_result['daily_pnl']

        # Reverse for display (most recent first)
        daily_volume = list(reversed(daily_pnl_data))

        # P&L by market from the calculator (includes redeems, merges, etc.)
        # Enrich with market titles via single batch query
        from .models import Market
        pnl_by_market = pnl_result.get('pnl_by_market', [])[:10]
        market_ids = [e.get('market_id') for e in pnl_by_market if e.get('market_id') and e.get('market_id') != 'unknown']
        markets_by_id = Market.objects.in_bulk(market_ids) if market_ids else {}
        for entry in pnl_by_market:
            market_id = entry.get('market_id')
            if market_id and market_id != 'unknown':
                market = markets_by_id.get(market_id)
                entry['market__title'] = market.title if market else f'Market #{market_id}'
            else:
                entry['market__title'] = 'Unknown'
            # Rename for frontend compatibility
            entry['estimated_pnl'] = entry.get('pnl', 0)
            entry['buy_volume'] = entry.get('buys', 0)
            entry['sell_volume'] = entry.get('sells', 0) + entry.get('redeems', 0)

        # ROI calculation based on calculated P&L
        # total_outflows = buys + splits (money spent)
        total_bought = pnl_result['totals'].get('total_buys', 0)
        all_time_pnl = pnl_result['total_pnl']
        period_pnl_value = pnl_result['period_pnl']
        # The headline PnL should reflect the selected period
        realized_pnl = period_pnl_value
        roi_percent = (realized_pnl / total_bought * 100) if total_bought > 0 else 0

        # Latest analysis with copy trading scenarios
        latest_analysis = latest_analysis_for_cache
        copy_trading_data = None
        analysis_metrics = None

        if latest_analysis:
            analysis_metrics = {
                # Nullable metrics: None when not available (may legitimately not exist)
                'win_rate_percent': float(latest_analysis.win_rate_percent) if latest_analysis.win_rate_percent is not None else None,
                'profit_factor': float(latest_analysis.profit_factor) if latest_analysis.profit_factor is not None else None,
                'max_drawdown_usd': float(latest_analysis.max_drawdown_usd) if latest_analysis.max_drawdown_usd is not None else None,
                # Numeric metrics: always have a value (0 is valid)
                'cash_flow_pnl': float(latest_analysis.cash_flow_pnl or 0),
                'buy_cost': float(latest_analysis.buy_cost or 0),
                'sell_revenue': float(latest_analysis.sell_revenue or 0),
                'redeem_revenue': float(latest_analysis.redeem_revenue or 0),
                'period_start_hours_ago': latest_analysis.period_start_hours_ago,
                'period_end_hours_ago': latest_analysis.period_end_hours_ago,
                'timestamp': latest_analysis.timestamp.isoformat(),
            }

            copy_scenarios = latest_analysis.copy_scenarios.all()
            if copy_scenarios:
                copy_trading_data = {
                    'scenarios': [
                        {
                            'slippage_value': float(s.slippage_value),
                            'slippage_mode': s.slippage_mode,
                            'total_trades_copied': s.total_trades_copied,
                            'total_volume_usd': float(s.total_volume_usd),
                            'original_pnl_usd': float(s.original_pnl_usd),
                            'estimated_copy_pnl_usd': float(s.estimated_copy_pnl_usd),
                            'pnl_difference_usd': float(s.pnl_difference_usd),
                            'pnl_difference_percent': float(s.pnl_difference_percent),
                            'profitable': s.profitable,
                        }
                        for s in copy_scenarios
                    ]
                }

        # Data completeness: check if markets with MERGE/REDEEM have corresponding BUY trades
        merge_redeem_market_ids = set(
            wallet.activities.filter(activity_type__in=['MERGE', 'REDEEM'])
            .exclude(market_id__isnull=True)
            .order_by().values_list('market_id', flat=True).distinct()
        )
        if merge_redeem_market_ids:
            markets_with_buys = set(
                wallet.trades.filter(market_id__in=merge_redeem_market_ids, side='BUY')
                .order_by().values_list('market_id', flat=True).distinct()
            )
            data_coverage_pct = round(len(markets_with_buys) / len(merge_redeem_market_ids) * 100, 1)
        else:
            data_coverage_pct = 100.0

        data = {
            'wallet': {
                'address': wallet.address,
                'name': wallet.name,
                'realized_pnl': realized_pnl,
                'unrealized_pnl': 0,
                'total_pnl': realized_pnl,
                'cash_flow_pnl': realized_pnl,
                'total_bought': total_bought,
                'roi_percent': round(roi_percent, 2),
                'selected_period': period,
                'last_updated': wallet.last_updated.isoformat() if wallet.last_updated else None,
                'data_start_date': wallet.data_start_date.isoformat() if wallet.data_start_date else None,
                'data_end_date': wallet.data_end_date.isoformat() if wallet.data_end_date else None,
            },
            'total_trades': trade_stats['total_trades'] or 0,
            'total_buys': trade_stats['total_buys'] or 0,
            'total_sells': trade_stats['total_sells'] or 0,
            'total_volume': float(trade_stats['total_volume'] or 0),
            'unique_markets': unique_markets,
            'activity_by_type': activity_by_type,
            'daily_pnl': daily_volume,
            'pnl_by_market': pnl_result.get('pnl_by_market', [])[:10],
            'positions': pnl_result.get('positions', [])[:20],
            'period_pnl': {
                'period': period,
                'calculated_pnl': period_pnl_value,
                'total_pnl': all_time_pnl,
                'note': 'P&L served from cached avg-cost replay data' if cache_valid else 'P&L served from last available cache snapshot'
            },
            'analysis_metrics': analysis_metrics,
            'copy_trading': copy_trading_data,
            'data_completeness': {
                'coverage_percent': data_coverage_pct,
                'warning': 'P&L may be inaccurate. Extend data range to capture earlier trades.' if data_coverage_pct < 80 else None,
            },
        }

        return Response(data)


class MarketViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoints for markets."""
    queryset = Market.objects.all()
    serializer_class = MarketSerializer

    @action(detail=True, methods=['get'])
    def trades(self, request, pk=None):
        """GET /api/markets/{id}/trades/ - Get market's trades."""
        market = self.get_object()
        trades = market.trades.all()[:100]
        serializer = TradeSerializer(trades, many=True)
        return Response(serializer.data)


class TradeViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoints for trades."""
    queryset = Trade.objects.select_related('wallet', 'market').all()
    serializer_class = TradeSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filter by wallet
        wallet_id = self.request.query_params.get('wallet')
        if wallet_id:
            queryset = queryset.filter(wallet_id=wallet_id)

        # Filter by side
        side = self.request.query_params.get('side')
        if side:
            queryset = queryset.filter(side=side.upper())

        return queryset[:500]


class ActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoints for activities."""
    queryset = Activity.objects.select_related('wallet', 'market').all()
    serializer_class = ActivitySerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filter by wallet
        wallet_id = self.request.query_params.get('wallet')
        if wallet_id:
            queryset = queryset.filter(wallet_id=wallet_id)

        # Filter by type
        activity_type = self.request.query_params.get('type')
        if activity_type:
            queryset = queryset.filter(activity_type=activity_type.upper())

        return queryset[:500]


class AnalysisRunViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoints for analysis runs."""
    queryset = AnalysisRun.objects.select_related('wallet').prefetch_related('copy_scenarios').all()
    serializer_class = AnalysisRunSerializer

    def get_serializer_class(self):
        if self.action == 'list':
            return AnalysisRunSummarySerializer
        return AnalysisRunSerializer


class DashboardView(APIView):
    """
    GET /api/dashboard/ - Dashboard statistics.
    """

    def get(self, request):
        # Overall stats
        total_wallets = Wallet.objects.count()
        total_trades = Trade.objects.count()
        total_volume = Trade.objects.aggregate(total=Sum('size'))['total'] or 0
        total_analyses = AnalysisRun.objects.count()

        # Top wallets by trades count
        top_wallets = Wallet.objects.annotate(
            trade_count=Count('trades'),
            unique_markets=Count('trades__market', distinct=True),
        ).order_by('-trade_count')[:5]

        # Recent analyses
        recent_analyses = AnalysisRun.objects.select_related('wallet').order_by('-timestamp')[:10]

        data = {
            'total_wallets': total_wallets,
            'total_trades': total_trades,
            'total_volume': total_volume,
            'total_analyses': total_analyses,
            'top_wallets': WalletSummarySerializer(top_wallets, many=True).data,
            'recent_analyses': AnalysisRunSummarySerializer(recent_analyses, many=True).data,
        }

        return Response(data)


def _bg_fetch_wallet(task_id, wallet_id, start_date=None, end_date=None):
    """Background task: fetch wallet data (runs in a daemon thread)."""
    import django
    from datetime import datetime, timedelta
    from django.db.models import Min, Max, Count
    from wallet_analysis.models import Wallet
    from wallet_analysis.services import DatabaseService
    from wallet_analysis.background import update_progress
    from src.api.polymarket_client import PolymarketClient
    from src.services.trade_service import TradeService
    from src.services.analytics_service import AnalyticsService
    from src.services.copy_trading_analyzer import CopyTradingAnalyzer

    # Close old DB connections for thread safety
    django.db.connections.close_all()

    wallet = Wallet.objects.get(pk=wallet_id)
    address = wallet.address
    update_progress(task_id, 5, 'initializing')

    db_service = DatabaseService()
    client = PolymarketClient()
    trade_service = TradeService(client)

    now = datetime.now()
    if end_date:
        end_dt = datetime.strptime(end_date, '%Y-%m-%d') if isinstance(end_date, str) else datetime.combine(end_date, datetime.max.time())
        before_timestamp = int(datetime.combine(end_dt.date(), datetime.max.time()).timestamp())
    else:
        before_timestamp = int(now.timestamp())

    if start_date:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d') if isinstance(start_date, str) else datetime.combine(start_date, datetime.min.time())
        after_timestamp = int(datetime.combine(start_dt.date(), datetime.min.time()).timestamp())
    else:
        after_timestamp = int(now.timestamp() - (30 * 24 * 3600))

    # Fetch
    update_progress(task_id, 10, 'fetching_activity')
    activity_result = trade_service.get_all_activity(address, after_timestamp, before_timestamp)
    trades = activity_result.get("trades", [])
    raw_activity = activity_result.get("raw_activity", {})
    cash_flow = activity_result.get("cash_flow", {})

    # Save
    update_progress(task_id, 50, 'saving_trades', trades_count=len(trades))
    if trades:
        db_service.save_trades(wallet, trades)
    if raw_activity:
        db_service.save_activities(wallet, raw_activity)

    # Update date range
    update_progress(task_id, 70, 'updating_wallet')
    trade_dates = wallet.trades.aggregate(min_date=Min('datetime'), max_date=Max('datetime'))
    activity_dates = wallet.activities.aggregate(min_date=Min('datetime'), max_date=Max('datetime'))
    actual_min = min(filter(None, [trade_dates['min_date'], activity_dates['min_date']]), default=None)
    actual_max = max(filter(None, [trade_dates['max_date'], activity_dates['max_date']]), default=None)
    if actual_min:
        wallet.data_start_date = actual_min.date() if hasattr(actual_min, 'date') else actual_min
    if actual_max:
        wallet.data_end_date = actual_max.date() if hasattr(actual_max, 'date') else actual_max
    wallet.save()

    # PnL — cache all periods
    update_progress(task_id, 80, 'calculating_pnl')
    from wallet_analysis.calculators.pnl_calculator import AvgCostBasisCalculator
    avg_cost_cache = {}
    try:
        calculator = AvgCostBasisCalculator(wallet.id)
        for p in ('ALL', '1M', '1W', '1D'):
            avg_cost_cache[p] = calculator.calculate(period=p)
        pnl_result = avg_cost_cache['ALL']
        wallet.subgraph_realized_pnl = pnl_result['total_pnl']
        wallet.subgraph_total_bought = pnl_result['totals'].get('total_buys', 0)
        wallet.save(update_fields=['subgraph_realized_pnl', 'subgraph_total_bought'])
    except Exception as e:
        print(f"PnL calc error (non-fatal): {e}")

    # Analytics
    update_progress(task_id, 90, 'running_analytics')
    if trades:
        analytics_service = AnalyticsService()
        copy_trading_analyzer = CopyTradingAnalyzer(use_percentage=False)
        analytics = analytics_service.analyze(trades)
        resolutions = analytics.pop("_resolutions", {})
        copy_analysis = copy_trading_analyzer.analyze(trades, resolutions, cash_flow)
        db_service.save_market_resolutions(resolutions)
        period_hours = int((before_timestamp - after_timestamp) / 3600)
        db_service.save_analysis_run(
            wallet=wallet,
            summary=analytics.get("summary", {}),
            cash_flow=cash_flow,
            performance=analytics.get("performance", {}),
            period_start_hours=period_hours,
            period_end_hours=0,
        )

    return {
        'status': 'success',
        'wallet_id': wallet_id,
        'trades_count': len(trades),
        'realized_pnl': float(wallet.subgraph_realized_pnl or 0),
    }


@api_view(['POST'])
def add_wallet(request):
    """
    POST /api/wallets/add/ - Add a new wallet to track.

    Body: {"address": "0x...", "name": "Optional name"}
    """
    from wallet_analysis.services import DatabaseService
    from wallet_analysis.background import run_in_background

    address = request.data.get('address', '').strip().lower()
    name = request.data.get('name', '')

    if not address or not address.startswith('0x') or len(address) != 42:
        return Response({'error': 'Invalid wallet address'}, status=status.HTTP_400_BAD_REQUEST)

    db_service = DatabaseService()

    # Check if wallet already exists
    existing = Wallet.objects.filter(address=address).first()
    if existing:
        return Response({
            'wallet_id': existing.id,
            'address': existing.address,
            'status': 'exists',
            'message': 'Wallet already tracked'
        })

    # Create wallet
    wallet = db_service.get_or_create_wallet(address, name=name)

    # Start background fetch (no Celery needed)
    task_id = run_in_background(_bg_fetch_wallet, wallet.id)

    return Response({
        'wallet_id': wallet.id,
        'address': wallet.address,
        'task_id': task_id,
        'status': 'added',
        'message': 'Wallet added, fetching data in background...'
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def refresh_wallet(request, pk):
    """
    POST /api/wallets/{id}/refresh/ - Refresh wallet data.
    """
    from wallet_analysis.background import run_in_background

    try:
        wallet = Wallet.objects.get(pk=pk)
    except Wallet.DoesNotExist:
        return Response({'error': 'Wallet not found'}, status=status.HTTP_404_NOT_FOUND)

    task_id = run_in_background(_bg_fetch_wallet, wallet.id)

    return Response({
        'status': 'refreshing',
        'task_id': task_id,
        'message': 'Wallet refresh started in background'
    })


@api_view(['GET'])
def task_status(request, task_id):
    """
    GET /api/tasks/{task_id}/ - Get status of a background task.
    """
    from wallet_analysis.background import get_task

    info = get_task(task_id)

    response = {
        'task_id': task_id,
        'status': info.get('status', 'UNKNOWN'),
    }

    if info.get('status') == 'PROGRESS':
        response['progress'] = {
            'stage': info.get('stage', ''),
            'progress': info.get('progress', 0),
        }
    elif info.get('status') == 'SUCCESS':
        response['result'] = info.get('result')
    elif info.get('status') == 'FAILURE':
        response['error'] = info.get('error')

    return Response(response)


@api_view(['DELETE'])
def delete_wallet(request, pk):
    """
    DELETE /api/wallets/{id}/ - Remove a wallet from tracking.
    """
    try:
        wallet = Wallet.objects.get(pk=pk)
        address = wallet.address
        wallet.delete()
        return Response({'status': 'deleted', 'address': address})
    except Wallet.DoesNotExist:
        return Response({'error': 'Wallet not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['PATCH'])
def update_wallet(request, pk):
    """
    PATCH /api/wallets/{id}/update/ - Update wallet details (name).

    Body: {"name": "New name"}
    """
    try:
        wallet = Wallet.objects.get(pk=pk)
    except Wallet.DoesNotExist:
        return Response({'error': 'Wallet not found'}, status=status.HTTP_404_NOT_FOUND)

    name = request.data.get('name')
    if name is not None:
        wallet.name = name.strip()
        wallet.save(update_fields=['name'])

    return Response({
        'status': 'updated',
        'wallet_id': wallet.id,
        'name': wallet.name,
    })


@api_view(['POST'])
def extend_wallet_range(request, pk):
    """
    POST /api/wallets/{id}/extend-range/ - Extend the date range for a wallet.

    Body: {"direction": "backward" | "forward" | "all", "days": 30}
    Or: {"start_date": "2024-01-01", "end_date": "2024-01-31"}
    """
    from datetime import datetime, timedelta
    from wallet_analysis.background import run_in_background

    try:
        wallet = Wallet.objects.get(pk=pk)
    except Wallet.DoesNotExist:
        return Response({'error': 'Wallet not found'}, status=status.HTTP_404_NOT_FOUND)

    direction = request.data.get('direction')
    days = request.data.get('days', 30)
    start_date_str = request.data.get('start_date')
    end_date_str = request.data.get('end_date')

    # Parse explicit dates if provided
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)
    elif direction == 'backward':
        current_start = wallet.data_start_date or datetime.now().date()
        end_date = current_start - timedelta(days=1)
        start_date = end_date - timedelta(days=days)
    elif direction == 'forward':
        current_end = wallet.data_end_date or datetime.now().date()
        start_date = current_end + timedelta(days=1)
        end_date = min(start_date + timedelta(days=days), datetime.now().date())
    elif direction == 'all':
        start_date = datetime(2020, 1, 1).date()
        end_date = datetime.now().date()
    else:
        return Response({'error': 'Provide direction (backward/forward/all) or start_date/end_date'}, status=status.HTTP_400_BAD_REQUEST)

    task_id = run_in_background(
        _bg_fetch_wallet, wallet.id,
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d'),
    )

    return Response({
        'status': 'extending',
        'task_id': task_id,
        'message': f'Fetching data from {start_date} to {end_date}',
        'start_date': str(start_date),
        'end_date': str(end_date),
    })


def _refresh_wallet_data(wallet, timeout_minutes=5, start_date=None, end_date=None):
    """
    Internal function to refresh wallet data with timeout.

    Args:
        wallet: Wallet instance
        timeout_minutes: Max time for operation
        start_date: Optional start date (datetime.date) - if None, uses 30 days ago
        end_date: Optional end date (datetime.date) - if None, uses today
    """
    from datetime import datetime, timedelta

    from src.api.polymarket_client import PolymarketClient
    from src.services.trade_service import TradeService
    from src.services.analytics_service import AnalyticsService
    from src.services.copy_trading_analyzer import CopyTradingAnalyzer
    from wallet_analysis.services import DatabaseService

    db_service = DatabaseService()
    client = PolymarketClient()
    trade_service = TradeService(client)
    analytics_service = AnalyticsService()
    copy_trading_analyzer = CopyTradingAnalyzer(use_percentage=False)  # Use points mode

    address = wallet.address

    # Calculate time range
    now = datetime.now()
    if end_date:
        end_dt = datetime.combine(end_date, datetime.max.time())
        before_timestamp = int(end_dt.timestamp())
    else:
        before_timestamp = int(now.timestamp())
        end_date = now.date()

    if start_date:
        start_dt = datetime.combine(start_date, datetime.min.time())
        after_timestamp = int(start_dt.timestamp())
    else:
        after_timestamp = int(now.timestamp() - (720 * 60 * 60))  # 30 days
        start_date = (now - timedelta(days=30)).date()

    try:
        # Fetch activity with implicit timeout from requests
        activity_result = trade_service.get_all_activity(address, after_timestamp, before_timestamp)
        trades = activity_result.get("trades", [])
        raw_activity = activity_result.get("raw_activity", {})
        cash_flow = activity_result.get("cash_flow", {})
        activity_errors = raw_activity.get("_errors", {})
        non_trade_activity_count = sum(
            len(items)
            for activity_type, items in raw_activity.items()
            if activity_type not in ("TRADE", "_errors") and isinstance(items, list)
        )
        print(
            f"Fetched activity for {address}: trades={len(trades)} "
            f"non_trade_activities={non_trade_activity_count} errors={activity_errors}"
        )

        # Save trades
        if trades:
            db_service.save_trades(wallet, trades)
        if raw_activity:
            db_service.save_activities(wallet, raw_activity)

        # Update date range from actual saved data (not request params)
        trade_dates = wallet.trades.aggregate(min_date=Min('datetime'), max_date=Max('datetime'))
        activity_dates = wallet.activities.aggregate(min_date=Min('datetime'), max_date=Max('datetime'))
        actual_min = min(filter(None, [trade_dates['min_date'], activity_dates['min_date']]), default=None)
        actual_max = max(filter(None, [trade_dates['max_date'], activity_dates['max_date']]), default=None)
        if actual_min:
            wallet.data_start_date = actual_min.date() if hasattr(actual_min, 'date') else actual_min
        if actual_max:
            wallet.data_end_date = actual_max.date() if hasattr(actual_max, 'date') else actual_max

        wallet.save()

        # Keep wallet-level cached P&L consistent with the avg cost calculator.
        from wallet_analysis.calculators.pnl_calculator import AvgCostBasisCalculator
        pnl_result = AvgCostBasisCalculator(wallet.id).calculate(period='ALL')
        wallet.subgraph_realized_pnl = pnl_result['total_pnl']
        wallet.subgraph_total_bought = pnl_result['totals'].get('total_buys', 0)
        wallet.save(update_fields=['subgraph_realized_pnl', 'subgraph_total_bought'])

        # Run analytics if we have trades
        if trades:
            analytics = analytics_service.analyze(trades)
            resolutions = analytics.pop("_resolutions", {})

            # Copy trading simulation
            copy_analysis = copy_trading_analyzer.analyze(trades, resolutions, cash_flow)

            # Save analysis run
            db_service.save_market_resolutions(resolutions)
            analysis_run = db_service.save_analysis_run(
                wallet=wallet,
                summary=analytics.get("summary", {}),
                cash_flow=cash_flow,
                performance=analytics.get("performance", {}),
                period_start_hours=720,
                period_end_hours=0,
            )
            db_service.save_copy_trading_scenarios(analysis_run, copy_analysis.get("scenarios", []))

        return True

    except Exception as e:
        print(f"Error refreshing wallet {address}: {e}")
        return False


@api_view(['POST'])
def analyze_wallet(request):
    """
    POST /api/analyze/ - Trigger analysis for a wallet (legacy endpoint).
    """
    address = request.data.get('address', '').strip().lower()
    if not address:
        return Response({'error': 'address is required'}, status=status.HTTP_400_BAD_REQUEST)

    from wallet_analysis.services import DatabaseService
    db_service = DatabaseService()

    wallet = db_service.get_or_create_wallet(address)

    try:
        success = _refresh_wallet_data(wallet, timeout_minutes=5)
        if success:
            wallet.refresh_from_db()
            return Response({
                'wallet_id': wallet.id,
                'address': wallet.address,
                'trades_count': wallet.trades.count(),
            })
        else:
            return Response({'error': 'Failed to fetch wallet data'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
