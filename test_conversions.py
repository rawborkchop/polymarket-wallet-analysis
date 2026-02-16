"""Test whether CONVERSIONs account for the ~$889 PnL gap."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
django.setup()

from decimal import Decimal
from django.db.models import Sum, Q, Count
from wallet_analysis.models import Activity, Trade, Market

WALLET_ID = 7
OFFICIAL_PNL = Decimal('20172.77')
V3_PNL = Decimal('19283.18')
GAP = OFFICIAL_PNL - V3_PNL

print(f"{'='*70}")
print(f"CONVERSION ANALYSIS - Testing PnL Gap Hypotheses")
print(f"{'='*70}")
print(f"V3 PnL:          ${V3_PNL:>12}")
print(f"Official PnL:     ${OFFICIAL_PNL:>12}")
print(f"Gap:              ${GAP:>12}")
print()

# Get all conversions
convs = Activity.objects.filter(wallet_id=WALLET_ID, activity_type='CONVERSION')
total_conv = convs.aggregate(t=Sum('usdc_size'))['t'] or Decimal('0')
conv_count = convs.count()
conv_markets = convs.values('market_id').distinct().count()

print(f"Total conversions: {conv_count} across {conv_markets} markets")
print(f"Total conversion USDC: ${total_conv:,.2f}")
print()

# ============================================================
# 1. Simple add
# ============================================================
print(f"{'='*70}")
print("HYPOTHESIS 1: V3 + all conversions")
h1 = V3_PNL + total_conv
print(f"  Result: ${h1:,.2f}  (diff from official: ${h1 - OFFICIAL_PNL:+,.2f})")
print()

# ============================================================
# 2. Net conversions - examine data patterns
# ============================================================
print(f"{'='*70}")
print("HYPOTHESIS 2: Net conversions - look for direction patterns")
print()

# Check fields that might indicate direction
sample = convs[:5]
for c in sample:
    print(f"  tx={c.transaction_hash[:12]}.. market={c.market_id} "
          f"size={c.size} usdc={c.usdc_size} outcome='{c.outcome}' asset='{c.asset[:20]}'")
print()

# Group by outcome
by_outcome = convs.values('outcome').annotate(
    total=Sum('usdc_size'), cnt=Count('id')
).order_by('-total')
print("  By outcome:")
for row in by_outcome:
    print(f"    {row['outcome'] or '(empty)'}: ${row['total']:,.2f} ({row['cnt']} records)")
print()

# Check if size vs usdc_size differ (might indicate direction)
pos_size = convs.filter(size__gt=0).aggregate(t=Sum('usdc_size'))['t'] or 0
neg_size = convs.filter(size__lt=0).aggregate(t=Sum('usdc_size'))['t'] or 0
zero_size = convs.filter(size=0).aggregate(t=Sum('usdc_size'))['t'] or 0
print(f"  By size sign: positive={pos_size}, negative={neg_size}, zero={zero_size}")

# Check if usdc_size has negatives
pos_usdc = convs.filter(usdc_size__gt=0).aggregate(t=Sum('usdc_size'))['t'] or 0
neg_usdc = convs.filter(usdc_size__lt=0).aggregate(t=Sum('usdc_size'))['t'] or 0
print(f"  By usdc_size sign: positive=${pos_usdc:,.2f}, negative=${neg_usdc:,.2f}")
net_conv = pos_usdc + neg_usdc
print(f"  Net conversion value: ${net_conv:,.2f}")
h2 = V3_PNL + net_conv
print(f"  V3 + net conversions: ${h2:,.2f}  (diff from official: ${h2 - OFFICIAL_PNL:+,.2f})")
print()

# ============================================================
# 3. Partial conversion - find best multiplier
# ============================================================
print(f"{'='*70}")
print("HYPOTHESIS 3: V3 + conversions × X")
print()

needed = GAP  # what we need to add to V3
if total_conv != 0:
    best_x = needed / total_conv
    print(f"  Exact X needed: {best_x:.6f} (i.e., {best_x*100:.4f}%)")
    print()
    for x in [Decimal('0.01'), Decimal('0.02'), Decimal('0.04'), Decimal('0.05'),
              Decimal('0.10'), best_x, Decimal('0.50'), Decimal('1.0')]:
        result = V3_PNL + total_conv * x
        diff = result - OFFICIAL_PNL
        marker = " <-- EXACT" if x == best_x else ""
        print(f"  X={float(x):8.4f}: ${result:>12,.2f}  (diff: ${diff:+,.2f}){marker}")
print()

# ============================================================
# 4. Per-market analysis
# ============================================================
print(f"{'='*70}")
print("HYPOTHESIS 4: Per-market analysis - conversions vs trades")
print()

conv_by_market = convs.values('market_id', 'market__title').annotate(
    conv_total=Sum('usdc_size'), conv_count=Count('id')
).order_by('-conv_total')

markets_with_trades = 0
markets_without_trades = 0
conv_with_trades_total = Decimal('0')
conv_without_trades_total = Decimal('0')

print(f"  {'Market':<45} {'Conv$':>10} {'#Conv':>5} {'#Trades':>7} {'Buy$':>10} {'Sell$':>10}")
print(f"  {'-'*45} {'-'*10} {'-'*5} {'-'*7} {'-'*10} {'-'*10}")

for row in conv_by_market[:20]:  # Top 20
    mid = row['market_id']
    trades = Trade.objects.filter(wallet_id=WALLET_ID, market_id=mid)
    trade_count = trades.count()
    buy_total = trades.filter(side='BUY').aggregate(t=Sum('total_value'))['t'] or 0
    sell_total = trades.filter(side='SELL').aggregate(t=Sum('total_value'))['t'] or 0
    
    title = (row['market__title'] or '')[:44]
    print(f"  {title:<45} ${row['conv_total']:>9,.2f} {row['conv_count']:>5} {trade_count:>7} ${buy_total:>9,.2f} ${sell_total:>9,.2f}")
    
    if trade_count > 0:
        markets_with_trades += 1
        conv_with_trades_total += row['conv_total']
    else:
        markets_without_trades += 1
        conv_without_trades_total += row['conv_total']

print()
print(f"  Markets with trades: {markets_with_trades}, conv total: ${conv_with_trades_total:,.2f}")
print(f"  Markets without trades: {markets_without_trades}, conv total: ${conv_without_trades_total:,.2f}")

# Test: only count conversions in markets WITH trades
h4a = V3_PNL + conv_with_trades_total
print(f"  V3 + conv(with trades only): ${h4a:,.2f}  (diff: ${h4a - OFFICIAL_PNL:+,.2f})")
h4b = V3_PNL + conv_without_trades_total
print(f"  V3 + conv(without trades only): ${h4b:,.2f}  (diff: ${h4b - OFFICIAL_PNL:+,.2f})")
print()

# ============================================================
# 5. Conversion as cost reduction
# ============================================================
print(f"{'='*70}")
print("HYPOTHESIS 5: Conversion as cost basis reduction")
print()

# For markets with conversions, compute trade PnL and see if conversion fills the gap
total_market_gap = Decimal('0')
print("  Per-market: trade_pnl vs trade_pnl + conversion")
print(f"  {'Market':<40} {'TradePnL':>10} {'Conv':>10} {'Combined':>10}")
print(f"  {'-'*40} {'-'*10} {'-'*10} {'-'*10}")

for row in conv_by_market[:15]:
    mid = row['market_id']
    trades = Trade.objects.filter(wallet_id=WALLET_ID, market_id=mid)
    buy_total = trades.filter(side='BUY').aggregate(t=Sum('total_value'))['t'] or Decimal('0')
    sell_total = trades.filter(side='SELL').aggregate(t=Sum('total_value'))['t'] or Decimal('0')
    
    # Also get redeems/merges for this market
    redeems = Activity.objects.filter(
        wallet_id=WALLET_ID, market_id=mid, activity_type='REDEEM'
    ).aggregate(t=Sum('usdc_size'))['t'] or Decimal('0')
    merges = Activity.objects.filter(
        wallet_id=WALLET_ID, market_id=mid, activity_type='MERGE'
    ).aggregate(t=Sum('usdc_size'))['t'] or Decimal('0')
    splits = Activity.objects.filter(
        wallet_id=WALLET_ID, market_id=mid, activity_type='SPLIT'
    ).aggregate(t=Sum('usdc_size'))['t'] or Decimal('0')
    
    trade_pnl = sell_total + redeems + merges - buy_total - splits
    conv_val = row['conv_total']
    combined = trade_pnl + conv_val
    
    title = (row['market__title'] or '')[:39]
    print(f"  {title:<40} ${trade_pnl:>9,.2f} ${conv_val:>9,.2f} ${combined:>9,.2f}")

print()

# ============================================================
# 6. Check transaction-level: are conversions paired with other activities?
# ============================================================
print(f"{'='*70}")
print("BONUS: Check if conversions share tx hashes with other activity types")
print()

conv_txs = set(convs.values_list('transaction_hash', flat=True))
other_activities = Activity.objects.filter(
    wallet_id=WALLET_ID,
    transaction_hash__in=conv_txs
).exclude(activity_type='CONVERSION')

shared_count = other_activities.count()
print(f"  Conversion tx hashes: {len(conv_txs)}")
print(f"  Other activities sharing those tx hashes: {shared_count}")

if shared_count > 0:
    by_type = other_activities.values('activity_type').annotate(
        cnt=Count('id'), total=Sum('usdc_size')
    )
    for row in by_type:
        print(f"    {row['activity_type']}: {row['cnt']} records, ${row['total']:,.2f}")

# Also check trades sharing tx hashes
shared_trades = Trade.objects.filter(
    wallet_id=WALLET_ID,
    transaction_hash__in=conv_txs
)
print(f"  Trades sharing conversion tx hashes: {shared_trades.count()}")

print()
print(f"{'='*70}")
print("SUMMARY")
print(f"{'='*70}")
print(f"  Gap to explain: ${GAP:,.2f}")
print(f"  Best multiplier X: {float(best_x):.6f} ({float(best_x)*100:.4f}% of conversions)")
print(f"  Net conversions (if signed): ${net_conv:,.2f}")
