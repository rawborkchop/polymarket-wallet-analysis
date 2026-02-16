"""Debug 30-day PnL overcounting for 1pixel wallet."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
django.setup()

from datetime import date, datetime
from decimal import Decimal
from collections import defaultdict
from wallet_analysis.models import Wallet, Trade, Activity, Market
from wallet_analysis.calculators.cost_basis_calculator import CostBasisPnLCalculator
from wallet_analysis.calculators.position_tracker import PositionTracker, ZERO

wallet = Wallet.objects.get(id=7)
print(f"Wallet: {wallet.name} ({wallet.address})")

START = date(2026, 1, 16)
END = date(2026, 2, 15)

# Run the filtered calculation
calc = CostBasisPnLCalculator()
result = calc.calculate_filtered(wallet, START, END)

print(f"\n=== FILTERED PnL ({START} to {END}) ===")
print(f"  Realized PnL (cost basis): ${result['total_realized_pnl']:.2f}")
print(f"  Full period PnL: ${result['full_period_pnl']:.2f}")
print(f"  Cash flow PnL: ${result['cash_flow_pnl']:.2f}")
print(f"  Unrealized: ${result['total_unrealized_pnl']:.2f}")

# Now let's dig into the raw events
provider = calc._provider
trades = provider.get_trades(wallet)
activities = provider.get_activities(wallet)

print(f"\n=== DATA COUNTS ===")
print(f"  Total trades: {len(trades)}")
print(f"  Total activities: {len(activities)}")

trades_in_period = [t for t in trades if START <= t.datetime.date() <= END]
activities_in_period = [a for a in activities if START <= a.datetime.date() <= END]
print(f"  Trades in period: {len(trades_in_period)}")
print(f"  Activities in period: {len(activities_in_period)}")

# Re-run tracker to get all realized events
market_resolutions = calc._build_market_resolutions(activities)
db_market_assets = calc._build_db_market_assets(wallet)
tracker = PositionTracker()
positions, all_events = tracker.process_events(trades, activities, market_resolutions, db_market_assets=db_market_assets)

# Filter events
filtered = [e for e in all_events if START <= e.datetime.date() <= END]
print(f"\n=== REALIZED EVENTS ===")
print(f"  Total realized events (all time): {len(all_events)}")
print(f"  Realized events in period: {len(filtered)}")
print(f"  Sum all-time: ${sum(e.amount for e in all_events):.2f}")
print(f"  Sum in period: ${sum(e.amount for e in filtered):.2f}")

# Group by event type - we need to know what kind of event generated each realized PnL
# The RealizedPnLEvent doesn't have event_type, so let's rebuild with that info
# Actually let's just look at what trades/activities happened in the period

print(f"\n=== ACTIVITIES IN PERIOD BY TYPE ===")
act_by_type = defaultdict(list)
for a in activities_in_period:
    act_by_type[a.activity_type].append(a)
for t, acts in sorted(act_by_type.items()):
    total_usdc = sum(Decimal(str(a.usdc_size)) for a in acts)
    print(f"  {t}: {len(acts)} activities, total USDC: ${total_usdc:.2f}")

print(f"\n=== TRADES IN PERIOD BY SIDE ===")
for side in ['BUY', 'SELL']:
    side_trades = [t for t in trades_in_period if t.side == side]
    total_val = sum(Decimal(str(t.total_value)) for t in side_trades)
    print(f"  {side}: {len(side_trades)} trades, total value: ${total_val:.2f}")

# Top 20 markets by PnL in the period
print(f"\n=== TOP 20 MARKETS BY PnL (in period) ===")
market_pnl = defaultdict(Decimal)
market_events = defaultdict(list)
for e in filtered:
    market_pnl[e.market_id] += e.amount
    market_events[e.market_id].append(e)

sorted_markets = sorted(market_pnl.items(), key=lambda x: abs(x[1]), reverse=True)[:20]

for i, (mid, pnl) in enumerate(sorted_markets, 1):
    # Get market title
    try:
        market = Market.objects.get(id=mid)
        title = market.title[:60]
    except:
        title = "Unknown"
    
    events = market_events[mid]
    
    # Count trades in period vs total for this market
    period_trades = Trade.objects.filter(wallet=wallet, market_id=mid, datetime__date__gte=START, datetime__date__lte=END).count()
    total_trades = Trade.objects.filter(wallet=wallet, market_id=mid).count()
    
    # Get first trade date for this market
    first_trade = Trade.objects.filter(wallet=wallet, market_id=mid).order_by('timestamp').first()
    first_date = first_trade.datetime.date() if first_trade else None
    
    # Check if position was opened before the period
    opened_before = first_date < START if first_date else False
    
    # Get position info
    pos_info = []
    for asset, pos in positions.items():
        if pos.market_id == str(mid):
            pos_info.append(pos)
    
    total_cost = sum(p.total_cost for p in pos_info)
    total_revenue = sum(p.total_revenue for p in pos_info)
    
    print(f"\n  {i}. {title}")
    print(f"     Market ID: {mid}")
    print(f"     Period PnL: ${pnl:.2f} ({len(events)} events)")
    print(f"     Trades: {period_trades} in period / {total_trades} total")
    print(f"     First trade: {first_date} {'[BEFORE PERIOD]' if opened_before else '[IN PERIOD]'}")
    print(f"     Total cost: ${total_cost:.2f}, Total revenue: ${total_revenue:.2f}")

# KEY ANALYSIS: How much PnL comes from positions opened BEFORE the period?
print(f"\n=== KEY ANALYSIS: PnL FROM PRE-PERIOD POSITIONS ===")
pnl_from_old = Decimal('0')
pnl_from_new = Decimal('0')
events_from_old = 0
events_from_new = 0

# For each realized event in the period, check when the position was first opened
market_first_trade = {}
for mid in set(e.market_id for e in filtered):
    first = Trade.objects.filter(wallet=wallet, market_id=mid).order_by('timestamp').first()
    if first:
        market_first_trade[str(mid)] = first.datetime.date()

for e in filtered:
    first_date = market_first_trade.get(str(e.market_id))
    if first_date and first_date < START:
        pnl_from_old += e.amount
        events_from_old += 1
    else:
        pnl_from_new += e.amount
        events_from_new += 1

print(f"  PnL from positions opened BEFORE {START}: ${pnl_from_old:.2f} ({events_from_old} events)")
print(f"  PnL from positions opened WITHIN period:  ${pnl_from_new:.2f} ({events_from_new} events)")
print(f"  Total: ${pnl_from_old + pnl_from_new:.2f}")

# Check: what does Polymarket 1M PnL actually mean?
# If Polymarket only counts PnL from positions OPENED in last month, 
# then our number is correct but measures something different.
print(f"\n=== HYPOTHESIS ===")
print(f"  Our 30-day realized PnL: ${sum(e.amount for e in filtered):.2f}")
print(f"  Polymarket 1M PnL: $1,282.17")
print(f"  Difference: ${float(sum(e.amount for e in filtered)) - 1282.17:.2f}")
print(f"")
print(f"  If Polymarket 1M = 'PnL on positions opened in last month':")
print(f"    -> PnL from new positions only = ${pnl_from_new:.2f}")
print(f"  If Polymarket 1M = 'PnL realized in last month (any open date)':")
print(f"    -> Our number should match, but it's ${sum(e.amount for e in filtered):.2f}")

# Let's also look at the BIGGEST single events to understand what's driving the number
print(f"\n=== TOP 20 INDIVIDUAL REALIZED EVENTS IN PERIOD ===")
sorted_events = sorted(filtered, key=lambda e: abs(e.amount), reverse=True)[:20]
for i, e in enumerate(sorted_events, 1):
    try:
        market = Market.objects.get(id=e.market_id)
        title = market.title[:50]
    except:
        title = "Unknown"
    first_date = market_first_trade.get(str(e.market_id), '?')
    print(f"  {i}. ${e.amount:>10.2f} | {e.datetime.date()} | {title} | first trade: {first_date}")

# NEW: Check if REDEEM events dominate and whether they're from old positions
print(f"\n=== REDEEM ANALYSIS ===")
redeem_activities_in_period = [a for a in activities_in_period if a.activity_type == 'REDEEM']
print(f"  REDEEMs in period: {len(redeem_activities_in_period)}")
total_redeem_usdc = sum(Decimal(str(a.usdc_size)) for a in redeem_activities_in_period)
print(f"  Total REDEEM USDC: ${total_redeem_usdc:.2f}")

# How many of these redeems are for markets where first buy was before the period?
old_redeems = 0
new_redeems = 0
for a in redeem_activities_in_period:
    mid = str(a.market_id) if a.market_id else None
    if mid and market_first_trade.get(mid) and market_first_trade[mid] < START:
        old_redeems += 1
    else:
        new_redeems += 1
print(f"  REDEEMs from pre-period positions: {old_redeems}")
print(f"  REDEEMs from in-period positions: {new_redeems}")
