"""Django REST Framework serializers for wallet analysis API."""

from rest_framework import serializers
from .models import (
    Wallet, Market, Trade, Activity, Position,
    CurrentPosition, AnalysisRun, CopyTradingScenario
)


class WalletSerializer(serializers.ModelSerializer):
    trades_count = serializers.SerializerMethodField()
    unique_markets = serializers.SerializerMethodField()
    realized_pnl = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = [
            'id', 'address', 'name', 'pseudonym',
            'realized_pnl', 'unique_markets',
            'first_seen', 'last_updated',
            'data_start_date', 'data_end_date', 'trades_count'
        ]

    def get_trades_count(self, obj):
        annotated = getattr(obj, 'trade_count', None)
        return annotated if annotated is not None else obj.trades.count()

    def get_unique_markets(self, obj):
        annotated = getattr(obj, 'unique_markets', None)
        if annotated is not None:
            return annotated
        return obj.trades.order_by().values('market_id').distinct().count()

    def get_realized_pnl(self, obj):
        """Return stored P&L (calculated on refresh)."""
        return float(obj.subgraph_realized_pnl or 0)


class WalletSummarySerializer(serializers.ModelSerializer):
    """Lightweight wallet serializer for lists."""
    trades_count = serializers.SerializerMethodField()
    unique_markets = serializers.SerializerMethodField()
    realized_pnl = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = [
            'id', 'address', 'name', 'realized_pnl',
            'unique_markets', 'last_updated',
            'data_start_date', 'data_end_date', 'trades_count'
        ]

    def get_trades_count(self, obj):
        annotated = getattr(obj, 'trade_count', None)
        return annotated if annotated is not None else obj.trades.count()

    def get_unique_markets(self, obj):
        annotated = getattr(obj, 'unique_markets', None)
        if annotated is not None:
            return annotated
        return obj.trades.order_by().values('market_id').distinct().count()

    def get_realized_pnl(self, obj):
        """Return stored P&L (calculated on refresh)."""
        return float(obj.subgraph_realized_pnl or 0)


class MarketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Market
        fields = [
            'id', 'condition_id', 'title', 'slug', 'resolved',
            'winning_outcome', 'end_date'
        ]


class TradeSerializer(serializers.ModelSerializer):
    market_title = serializers.CharField(source='market.title', read_only=True)
    wallet_address = serializers.CharField(source='wallet.address', read_only=True)

    class Meta:
        model = Trade
        fields = [
            'id', 'wallet_address', 'market_title', 'datetime',
            'side', 'outcome', 'price', 'size', 'total_value',
            'transaction_hash'
        ]


class ActivitySerializer(serializers.ModelSerializer):
    wallet_address = serializers.CharField(source='wallet.address', read_only=True)

    class Meta:
        model = Activity
        fields = [
            'id', 'wallet_address', 'activity_type', 'datetime',
            'size', 'usdc_size', 'title', 'transaction_hash'
        ]


class CopyTradingScenarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = CopyTradingScenario
        fields = [
            'slippage_value', 'slippage_mode', 'total_trades_copied',
            'total_volume_usd', 'original_pnl_usd', 'estimated_copy_pnl_usd',
            'pnl_difference_usd', 'pnl_difference_percent', 'profitable'
        ]


class AnalysisRunSerializer(serializers.ModelSerializer):
    wallet_address = serializers.CharField(source='wallet.address', read_only=True)
    copy_scenarios = CopyTradingScenarioSerializer(many=True, read_only=True)

    class Meta:
        model = AnalysisRun
        fields = [
            'id', 'wallet_address', 'timestamp',
            'period_start_hours_ago', 'period_end_hours_ago',
            'total_trades', 'total_buys', 'total_sells',
            'total_volume_usd', 'unique_markets',
            'buy_cost', 'sell_revenue', 'redeem_revenue',
            'cash_flow_pnl',
            'win_rate_percent', 'profit_factor', 'max_drawdown_usd',
            'copy_scenarios'
        ]


class AnalysisRunSummarySerializer(serializers.ModelSerializer):
    """Lightweight analysis serializer for lists."""
    wallet_address = serializers.CharField(source='wallet.address', read_only=True)

    class Meta:
        model = AnalysisRun
        fields = [
            'id', 'wallet_address', 'timestamp', 'total_trades',
            'total_volume_usd', 'cash_flow_pnl'
        ]


class WalletStatsSerializer(serializers.Serializer):
    """Statistics for a wallet's trading activity."""
    total_trades = serializers.IntegerField()
    total_buys = serializers.IntegerField()
    total_sells = serializers.IntegerField()
    total_volume = serializers.DecimalField(max_digits=20, decimal_places=2)
    unique_markets = serializers.IntegerField()
    activity_by_type = serializers.DictField()
    daily_volume = serializers.ListField()
    pnl_by_market = serializers.ListField()


class DashboardStatsSerializer(serializers.Serializer):
    """Overall dashboard statistics."""
    total_wallets = serializers.IntegerField()
    total_trades = serializers.IntegerField()
    total_volume = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_analyses = serializers.IntegerField()
    top_wallets = WalletSummarySerializer(many=True)
    recent_analyses = AnalysisRunSummarySerializer(many=True)
