"""Django admin configuration for wallet_analysis models."""

from django.contrib import admin
from .models import (
    Wallet, Market, Trade, Activity, Position,
    CurrentPosition, AnalysisRun, CopyTradingScenario
)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['address', 'name', 'pseudonym', 'data_start_date', 'data_end_date', 'last_updated']
    search_fields = ['address', 'name', 'pseudonym']
    list_filter = ['last_updated']
    readonly_fields = ['first_seen', 'last_updated']


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = ['title', 'condition_id', 'resolved', 'winning_outcome', 'end_date']
    search_fields = ['title', 'condition_id']
    list_filter = ['resolved', 'end_date']


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ['wallet', 'datetime', 'side', 'outcome', 'size', 'price', 'total_value']
    search_fields = ['wallet__address', 'transaction_hash']
    list_filter = ['side', 'datetime']
    raw_id_fields = ['wallet', 'market']


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ['wallet', 'datetime', 'activity_type', 'usdc_size', 'title']
    search_fields = ['wallet__address', 'title']
    list_filter = ['activity_type', 'datetime']
    raw_id_fields = ['wallet', 'market']


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ['wallet', 'token_id', 'amount', 'realized_pnl', 'total_bought']
    search_fields = ['wallet__address', 'token_id']
    list_filter = ['updated_at']
    raw_id_fields = ['wallet']


@admin.register(CurrentPosition)
class CurrentPositionAdmin(admin.ModelAdmin):
    list_display = ['wallet', 'outcome', 'size', 'current_value', 'cash_pnl', 'redeemable']
    search_fields = ['wallet__address', 'outcome']
    list_filter = ['redeemable', 'updated_at']
    raw_id_fields = ['wallet', 'market']


@admin.register(AnalysisRun)
class AnalysisRunAdmin(admin.ModelAdmin):
    list_display = [
        'wallet', 'timestamp', 'total_trades', 'total_volume_usd',
        'cash_flow_pnl', 'win_rate_percent'
    ]
    search_fields = ['wallet__address']
    list_filter = ['timestamp']
    raw_id_fields = ['wallet']


@admin.register(CopyTradingScenario)
class CopyTradingScenarioAdmin(admin.ModelAdmin):
    list_display = [
        'analysis_run', 'slippage_value', 'slippage_mode',
        'original_pnl_usd', 'estimated_copy_pnl_usd', 'profitable'
    ]
    list_filter = ['slippage_mode', 'profitable']
    raw_id_fields = ['analysis_run']
