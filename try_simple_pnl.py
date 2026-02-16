"""Test simple PnL hypothesis: PnL = sell_revenue + redeem_revenue - buy_cost"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from decimal import Decimal
from wallet_analysis.models import Trade, Activity

WALLET_ID = 7
TARGET = Decimal('20172.77')

# Load all trades
trades = Trade.objects.filter(wallet_id=WALLET_ID)
buys = trades.filter(side='BUY')
sells = trades.filter(side='SELL')

total_buy_cost = sum(t.price * t.size for t in buys)
total_sell_revenue = sum(t.price * t.size for t in sells)

print(f"Total trades: {trades.count()} (BUY: {buys.count()}, SELL: {sells.count()})")
print(f"Total buy cost:     ${total_buy_cost:.2f}")
print(f"Total sell revenue: ${total_sell_revenue:.2f}")

# Load activities
activities = Activity.objects.filter(wallet_id=WALLET_ID)
redeems = activities.filter(activity_type='REDEEM')
merges = activities.filter(activity_type='MERGE')
splits = activities.filter(activity_type='SPLIT')

total_redeem = sum(a.usdc_size for a in redeems)
total_merge = sum(a.usdc_size for a in merges)
total_split = sum(a.usdc_size for a in splits)

print(f"\nActivities: REDEEM={redeems.count()}, MERGE={merges.count()}, SPLIT={splits.count()}")
print(f"Total redeem revenue: ${total_redeem:.2f}")
print(f"Total merge revenue:  ${total_merge:.2f}")
print(f"Total split cost:     ${total_split:.2f}")

# Variant 1: Simple global (no market grouping needed for sums)
v1 = total_sell_revenue + total_redeem - total_buy_cost
print(f"\n{'='*60}")
print(f"V1: sell + redeem - buy = ${v1:.2f}")
print(f"    Diff from target: ${v1 - TARGET:.2f}")

# Variant 2: With merges and splits
v2 = total_sell_revenue + total_redeem + total_merge - total_buy_cost - total_split
print(f"\nV2: sell + redeem + merge - buy - split = ${v2:.2f}")
print(f"    Diff from target: ${v2 - TARGET:.2f}")

# Variant 3: Just sell - buy (trades only)
v3 = total_sell_revenue - total_buy_cost
print(f"\nV3: sell - buy (trades only) = ${v3:.2f}")
print(f"    Diff from target: ${v3 - TARGET:.2f}")

# Variant 4: Using total_value field instead of price*size
total_buy_tv = sum(t.total_value for t in buys)
total_sell_tv = sum(t.total_value for t in sells)
v4 = total_sell_tv + total_redeem - total_buy_tv
print(f"\nV4: sell_tv + redeem - buy_tv = ${v4:.2f}")
print(f"    Diff from target: ${v4 - TARGET:.2f}")

# Variant 5: sell_tv + redeem + merge - buy_tv - split
v5 = total_sell_tv + total_redeem + total_merge - total_buy_tv - total_split
print(f"\nV5: sell_tv + redeem + merge - buy_tv - split = ${v5:.2f}")
print(f"    Diff from target: ${v5 - TARGET:.2f}")

# Find closest
variants = {'V1': v1, 'V2': v2, 'V3': v3, 'V4': v4, 'V5': v5}
closest = min(variants, key=lambda k: abs(variants[k] - TARGET))
print(f"\n{'='*60}")
print(f"TARGET: ${TARGET}")
print(f"CLOSEST: {closest} = ${variants[closest]:.2f} (diff: ${variants[closest] - TARGET:.2f})")

# Also check: per-market grouping vs global (should be same for sums)
print(f"\n{'='*60}")
print("Per-market breakdown (top 10 by absolute PnL):")
market_pnl = {}
for t in trades:
    mid = t.market_id
    if mid not in market_pnl:
        market_pnl[mid] = {'buy': Decimal(0), 'sell': Decimal(0), 'redeem': Decimal(0)}
    if t.side == 'BUY':
        market_pnl[mid]['buy'] += t.price * t.size
    else:
        market_pnl[mid]['sell'] += t.price * t.size

for a in redeems:
    mid = a.market_id
    if mid not in market_pnl:
        market_pnl[mid] = {'buy': Decimal(0), 'sell': Decimal(0), 'redeem': Decimal(0)}
    market_pnl[mid]['redeem'] += a.usdc_size

market_pnls = {mid: d['sell'] + d['redeem'] - d['buy'] for mid, d in market_pnl.items()}
sorted_markets = sorted(market_pnls.items(), key=lambda x: abs(x[1]), reverse=True)

for mid, pnl in sorted_markets[:10]:
    d = market_pnl[mid]
    print(f"  Market {mid}: PnL=${pnl:.2f} (buy=${d['buy']:.2f}, sell=${d['sell']:.2f}, redeem=${d['redeem']:.2f})")

total_per_market = sum(market_pnls.values())
print(f"\nSum of per-market PnLs: ${total_per_market:.2f}")
print(f"Matches V1 global: {abs(total_per_market - v1) < Decimal('0.01')}")
