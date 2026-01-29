"""
Django models for Polymarket wallet analysis data.

These models provide structured storage for trades, positions, and analysis results.
"""

from django.db import models
from django.utils import timezone


class Wallet(models.Model):
    """Tracked wallet addresses."""

    address = models.CharField(max_length=42, unique=True, db_index=True)
    name = models.CharField(max_length=100, blank=True)
    pseudonym = models.CharField(max_length=100, blank=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    # Date range of fetched trade data
    data_start_date = models.DateField(null=True, blank=True)
    data_end_date = models.DateField(null=True, blank=True)

    # Cached P&L from subgraph (updated on each analysis)
    subgraph_realized_pnl = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    subgraph_total_bought = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    subgraph_total_positions = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-last_updated']

    def __str__(self):
        return self.name or self.pseudonym or self.address[:10]


class Market(models.Model):
    """Polymarket markets (conditions)."""

    condition_id = models.CharField(max_length=66, unique=True, db_index=True)
    title = models.CharField(max_length=500)
    slug = models.CharField(max_length=200, blank=True)
    icon = models.URLField(blank=True)
    end_date = models.DateField(null=True, blank=True)

    # Resolution data
    resolved = models.BooleanField(default=False)
    winning_outcome = models.CharField(max_length=100, blank=True)
    resolution_timestamp = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title[:50]


class Trade(models.Model):
    """Individual trades executed by wallets."""

    SIDE_CHOICES = [
        ('BUY', 'Buy'),
        ('SELL', 'Sell'),
    ]

    wallet = models.ForeignKey(
        Wallet, on_delete=models.CASCADE, related_name='trades'
    )
    market = models.ForeignKey(
        Market, on_delete=models.CASCADE, related_name='trades',
        null=True, blank=True
    )

    # Trade identifiers
    transaction_hash = models.CharField(max_length=66, db_index=True)
    asset = models.CharField(max_length=100, blank=True)

    # Trade details
    timestamp = models.IntegerField(db_index=True)
    datetime = models.DateTimeField(db_index=True)
    side = models.CharField(max_length=4, choices=SIDE_CHOICES)
    outcome = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=6)
    size = models.DecimalField(max_digits=20, decimal_places=6)
    total_value = models.DecimalField(max_digits=20, decimal_places=6)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['wallet', 'timestamp']),
            models.Index(fields=['wallet', 'side']),
        ]
        # Unique constraint to prevent duplicate trades
        constraints = [
            models.UniqueConstraint(
                fields=['transaction_hash', 'asset', 'size', 'price', 'side'],
                name='unique_trade'
            )
        ]

    def __str__(self):
        return f"{self.side} {self.size} @ {self.price}"

    @property
    def is_buy(self):
        return self.side == 'BUY'


class Activity(models.Model):
    """Non-trade activity (REDEEM, SPLIT, MERGE, REWARD)."""

    ACTIVITY_TYPES = [
        ('REDEEM', 'Redeem'),
        ('SPLIT', 'Split'),
        ('MERGE', 'Merge'),
        ('REWARD', 'Reward'),
        ('CONVERSION', 'Conversion'),
    ]

    wallet = models.ForeignKey(
        Wallet, on_delete=models.CASCADE, related_name='activities'
    )
    market = models.ForeignKey(
        Market, on_delete=models.CASCADE, related_name='activities',
        null=True, blank=True
    )

    activity_type = models.CharField(max_length=20, choices=ACTIVITY_TYPES, db_index=True)
    transaction_hash = models.CharField(max_length=66, db_index=True)
    timestamp = models.IntegerField(db_index=True)
    datetime = models.DateTimeField()
    size = models.DecimalField(max_digits=20, decimal_places=6)
    usdc_size = models.DecimalField(max_digits=20, decimal_places=6)
    title = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = 'Activities'
        indexes = [
            models.Index(fields=['wallet', 'activity_type']),
            models.Index(fields=['wallet', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.activity_type} ${self.usdc_size}"


class Position(models.Model):
    """
    Position data from the PnL subgraph.

    Represents a wallet's position in a specific token.
    """

    wallet = models.ForeignKey(
        Wallet, on_delete=models.CASCADE, related_name='positions'
    )
    token_id = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    avg_price = models.DecimalField(max_digits=10, decimal_places=6)
    realized_pnl = models.DecimalField(max_digits=20, decimal_places=2)
    total_bought = models.DecimalField(max_digits=20, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-realized_pnl']
        constraints = [
            models.UniqueConstraint(
                fields=['wallet', 'token_id'],
                name='unique_wallet_position'
            )
        ]

    def __str__(self):
        return f"Position {self.token_id[:10]} P&L: ${self.realized_pnl}"


class CurrentPosition(models.Model):
    """
    Current open positions from the /positions endpoint.

    These are positions the wallet currently holds.
    """

    wallet = models.ForeignKey(
        Wallet, on_delete=models.CASCADE, related_name='current_positions'
    )
    market = models.ForeignKey(
        Market, on_delete=models.CASCADE, related_name='current_positions',
        null=True, blank=True
    )

    asset = models.CharField(max_length=100)
    outcome = models.CharField(max_length=100)
    size = models.DecimalField(max_digits=20, decimal_places=6)
    avg_price = models.DecimalField(max_digits=10, decimal_places=6)
    initial_value = models.DecimalField(max_digits=20, decimal_places=2)
    current_value = models.DecimalField(max_digits=20, decimal_places=2)
    cash_pnl = models.DecimalField(max_digits=20, decimal_places=2)
    percent_pnl = models.DecimalField(max_digits=10, decimal_places=4)
    realized_pnl = models.DecimalField(max_digits=20, decimal_places=2)
    cur_price = models.DecimalField(max_digits=10, decimal_places=6)
    redeemable = models.BooleanField(default=False)
    end_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-initial_value']
        constraints = [
            models.UniqueConstraint(
                fields=['wallet', 'asset'],
                name='unique_wallet_current_position'
            )
        ]

    def __str__(self):
        return f"{self.outcome} {self.size} @ {self.cur_price}"


class AnalysisRun(models.Model):
    """
    Record of each analysis run performed on a wallet.

    Stores summary statistics and parameters used.
    """

    wallet = models.ForeignKey(
        Wallet, on_delete=models.CASCADE, related_name='analysis_runs'
    )
    timestamp = models.DateTimeField(default=timezone.now)

    # Analysis parameters
    period_start_hours_ago = models.IntegerField()
    period_end_hours_ago = models.IntegerField()

    # Trade summary
    total_trades = models.IntegerField(default=0)
    total_buys = models.IntegerField(default=0)
    total_sells = models.IntegerField(default=0)
    total_volume_usd = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    unique_markets = models.IntegerField(default=0)

    # Cash flow from activity API (may be incomplete)
    buy_cost = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    sell_revenue = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    redeem_revenue = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    split_cost = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    merge_revenue = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    reward_revenue = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    cash_flow_pnl = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    # Subgraph P&L (authoritative)
    subgraph_realized_pnl = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    subgraph_total_bought = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    subgraph_total_positions = models.IntegerField(null=True, blank=True)

    # Performance metrics
    win_rate_percent = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    profit_factor = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    max_drawdown_usd = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Analysis {self.wallet} @ {self.timestamp}"


class CopyTradingScenario(models.Model):
    """
    Copy trading simulation results.

    Stores the estimated P&L for copying a wallet with various slippage levels.
    """

    SLIPPAGE_MODES = [
        ('percentage', 'Percentage'),
        ('points', 'Points'),
    ]

    analysis_run = models.ForeignKey(
        AnalysisRun, on_delete=models.CASCADE, related_name='copy_scenarios'
    )

    slippage_value = models.DecimalField(max_digits=10, decimal_places=4)
    slippage_mode = models.CharField(max_length=20, choices=SLIPPAGE_MODES)

    total_trades_copied = models.IntegerField(default=0)
    total_volume_usd = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    original_pnl_usd = models.DecimalField(max_digits=20, decimal_places=2)
    estimated_copy_pnl_usd = models.DecimalField(max_digits=20, decimal_places=2)
    pnl_difference_usd = models.DecimalField(max_digits=20, decimal_places=2)
    pnl_difference_percent = models.DecimalField(max_digits=10, decimal_places=2)
    profitable = models.BooleanField(default=False)

    class Meta:
        ordering = ['slippage_value']

    def __str__(self):
        mode_str = '%' if self.slippage_mode == 'percentage' else 'pts'
        return f"Slippage {self.slippage_value}{mode_str}: ${self.estimated_copy_pnl_usd}"
