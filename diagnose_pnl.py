"""Diagnose PnL discrepancy between local calculation and Polymarket subgraph."""
import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from wallet_analysis.models import Wallet, Trade, Activity, Market
from wallet_analysis.calculators.position_tracker import PositionTracker

w = Wallet.objects.get(address='0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c')
trades = list(w.trades.select_related('market').order_by('timestamp'))
activities = list(w.activities.select_related('market').order_by('timestamp'))

print(f"Wallet: {w.address}")
print(f"Trades: {len(trades)}, Activities: {len(activities)}")
print(f"Subgraph PnL: ${w.subgraph_realized_pnl:,.2f}")

# Check activity types
from collections import Counter
act_types = Counter(a.activity_type for a in activities)
trade_sides = Counter(t.side for t in trades)
print(f"\nTrade sides: {dict(trade_sides)}")
print(f"Activity types: {dict(act_types)}")

# Check how many trades have asset/outcome
trades_with_asset = sum(1 for t in trades if t.asset)
trades_with_outcome = sum(1 for t in trades if t.outcome)
print(f"\nTrades with asset: {trades_with_asset}/{len(trades)}")
print(f"Trades with outcome: {trades_with_outcome}/{len(trades)}")

# Check activities
acts_with_asset = sum(1 for a in activities if a.asset)
acts_with_outcome = sum(1 for a in activities if a.outcome)
print(f"Activities with asset: {acts_with_asset}/{len(activities)}")
print(f"Activities with outcome: {acts_with_outcome}/{len(activities)}")

# Check market resolutions
resolved_markets = Market.objects.filter(resolved=True).exclude(winning_outcome='').count()
total_markets = Market.objects.count()
print(f"\nMarkets: {total_markets} total, {resolved_markets} resolved with outcome")

# Check for redeems without asset (the main problem)
redeems = [a for a in activities if a.activity_type == 'REDEEM']
redeems_no_asset = [a for a in redeems if not a.asset]
print(f"\nREDEEMs: {len(redeems)} total, {len(redeems_no_asset)} WITHOUT asset")

# Sum USDC of unresolvable redeems
unresolvable_usdc = sum(a.usdc_size for a in redeems_no_asset)
print(f"Unresolvable REDEEM USDC: ${unresolvable_usdc:,.2f}")

# Run position tracker to see how many events get skipped
tracker = PositionTracker()
market_resolutions = {}
try:
    resolved = Market.objects.filter(resolved=True).exclude(winning_outcome='')
    market_resolutions = {str(m.id): m.winning_outcome for m in resolved}
except:
    pass

positions, events = tracker.process_events(trades, activities, market_resolutions)
total_realized = sum(e.amount for e in events)
print(f"\nPosition tracker realized PnL: ${float(total_realized):,.2f}")
print(f"Realized events: {len(events)}")

# Compare: what % of trades/activities contribute to cost basis
print(f"\n--- Potential gaps ---")
# Trades without asset can't be tracked
trades_no_asset = [t for t in trades if not t.asset]
buys_no_asset = [t for t in trades_no_asset if t.side == 'BUY']
sells_no_asset = [t for t in trades_no_asset if t.side == 'SELL']
print(f"Trades without asset: {len(trades_no_asset)} (BUY: {len(buys_no_asset)}, SELL: {len(sells_no_asset)})")
buy_value_no_asset = sum(t.total_value for t in buys_no_asset)
sell_value_no_asset = sum(t.total_value for t in sells_no_asset)
print(f"  BUY value missing: ${float(buy_value_no_asset):,.2f}")
print(f"  SELL value missing: ${float(sell_value_no_asset):,.2f}")
