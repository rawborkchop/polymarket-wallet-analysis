"""Simple cash-flow PnL for wallet id=7, 2026-01-16 to 2026-02-15."""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from datetime import datetime, timezone
from decimal import Decimal
from wallet_analysis.models import Trade, Activity

WALLET_ID = 7
START = datetime(2026, 1, 16, tzinfo=timezone.utc)
END = datetime(2026, 2, 15, 23, 59, 59, tzinfo=timezone.utc)

print(f"Period: {START.date()} to {END.date()}")
print(f"Wallet ID: {WALLET_ID}")
print("=" * 60)

# Trades
trades = Trade.objects.filter(wallet_id=WALLET_ID, datetime__gte=START, datetime__lte=END)
buys = trades.filter(side='BUY')
sells = trades.filter(side='SELL')

buy_cost = sum(t.price * t.size for t in buys)
sell_revenue = sum(t.price * t.size for t in sells)

print(f"\nTrades in period: {trades.count()} (BUY: {buys.count()}, SELL: {sells.count()})")
print(f"  Buy cost (outflows):    ${buy_cost:,.6f}")
print(f"  Sell revenue (inflows): ${sell_revenue:,.6f}")
print(f"  Trade-only PnL:         ${sell_revenue - buy_cost:,.6f}")

# Activities
activities = Activity.objects.filter(wallet_id=WALLET_ID, datetime__gte=START, datetime__lte=END)
print(f"\nActivities in period: {activities.count()}")

for atype in ['REDEEM', 'SPLIT', 'MERGE', 'REWARD', 'CONVERSION']:
    subset = activities.filter(activity_type=atype)
    total = sum(a.usdc_size for a in subset)
    print(f"  {atype}: count={subset.count()}, total_usdc=${total:,.6f}")

redeem_inflows = sum(a.usdc_size for a in activities.filter(activity_type='REDEEM'))
split_outflows = sum(a.usdc_size for a in activities.filter(activity_type='SPLIT'))
merge_inflows = sum(a.usdc_size for a in activities.filter(activity_type='MERGE'))

print(f"\n--- Cash Flow PnL (excluding CONVERSION/REWARD) ---")
print(f"  Sell revenue:    +${sell_revenue:,.2f}")
print(f"  Buy cost:        -${buy_cost:,.2f}")
print(f"  Redeem inflows:  +${redeem_inflows:,.2f}")
print(f"  Split outflows:  -${split_outflows:,.2f}")
print(f"  Merge inflows:   +${merge_inflows:,.2f}")

pnl = sell_revenue - buy_cost + redeem_inflows - split_outflows + merge_inflows
print(f"\n  TOTAL CASH FLOW PnL: ${pnl:,.2f}")
print(f"  Polymarket official: $1,282.17")
print(f"  Difference:          ${pnl - Decimal('1282.17'):,.2f}")
