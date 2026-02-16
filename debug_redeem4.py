"""Check total cash flows to understand the gap."""
import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity
from decimal import Decimal

w = Wallet.objects.get(address__startswith='0xbdcd')

# Cash flow approach: total money in vs total money out
trades = Trade.objects.filter(wallet=w)
activities = Activity.objects.filter(wallet=w)

buy_total = sum(Decimal(str(t.total_value)) for t in trades.filter(side='BUY'))
sell_total = sum(Decimal(str(t.total_value)) for t in trades.filter(side='SELL'))

redeem_total = sum(Decimal(str(a.usdc_size)) for a in activities.filter(activity_type='REDEEM'))
split_total = sum(Decimal(str(a.usdc_size)) for a in activities.filter(activity_type='SPLIT'))
merge_total = sum(Decimal(str(a.usdc_size)) for a in activities.filter(activity_type='MERGE'))
reward_total = sum(Decimal(str(a.usdc_size)) for a in activities.filter(activity_type='REWARD'))

print(f"=== Cash Flows for {w.address[:10]} ===")
print(f"BUY (outflow):   ${buy_total:,.2f}")
print(f"SELL (inflow):   ${sell_total:,.2f}")
print(f"SPLIT (outflow): ${split_total:,.2f}")
print(f"MERGE (inflow):  ${merge_total:,.2f}")
print(f"REDEEM (inflow): ${redeem_total:,.2f}")
print(f"REWARD (inflow): ${reward_total:,.2f}")

cash_pnl = (sell_total + redeem_total + merge_total + reward_total) - (buy_total + split_total)
print(f"\nCash Flow PnL: ${cash_pnl:,.2f}")
print(f"Subgraph PnL:  ${w.subgraph_realized_pnl:,.2f}")
print(f"Gap:           ${w.subgraph_realized_pnl - cash_pnl:,.2f}")

# Check: are there open positions (unrealized)?
from wallet_analysis.calculators.position_tracker import PositionTracker
tracker = PositionTracker()
trades_list = list(Trade.objects.filter(wallet=w).order_by('timestamp'))
activities_list = list(Activity.objects.filter(wallet=w).order_by('timestamp'))
positions, _ = tracker.process_events(trades_list, activities_list)
unrealized = Decimal('0')
open_count = 0
for a, p in positions.items():
    if p.quantity > 0:
        open_count += 1
        # unrealized at current value (assume market price = ?)
        # For now just show cost basis
        unrealized += p.quantity * (Decimal('1') - p.avg_price) if p.avg_price < Decimal('0.5') else p.quantity * (Decimal('0') - p.avg_price)

print(f"\nOpen positions: {open_count}")
open_value = sum(p.quantity * p.avg_price for _, p in positions.items() if p.quantity > 0)
print(f"Open position cost basis: ${open_value:,.2f}")
