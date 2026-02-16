"""Deeper analysis: check if PM PnL = realized + unrealized (mark-to-market)."""
import os, sys, json, urllib.request
from datetime import datetime, timedelta
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
import django
django.setup()

from wallet_analysis.models import Trade, Activity, Wallet, CurrentPosition, Position
from django.db.models import Sum

wallet_id = 7

# Check current positions for unrealized PnL
positions = CurrentPosition.objects.filter(wallet_id=wallet_id)
print(f"Current positions: {positions.count()}")
total_unrealized = sum(float(p.current_value - p.initial_value) for p in positions)
total_cash_pnl = sum(float(p.cash_pnl) for p in positions)
total_realized = sum(float(p.realized_pnl) for p in positions)
print(f"Sum current_value - initial_value (unrealized): ${total_unrealized:.2f}")
print(f"Sum cash_pnl: ${total_cash_pnl:.2f}")
print(f"Sum realized_pnl: ${total_realized:.2f}")

# Check Position model (from subgraph)
subgraph_positions = Position.objects.filter(wallet_id=wallet_id)
total_subgraph_realized = sum(float(p.realized_pnl) for p in subgraph_positions)
total_subgraph_bought = sum(float(p.total_bought) for p in subgraph_positions)
print(f"\nSubgraph positions: {subgraph_positions.count()}")
print(f"Sum subgraph realized_pnl: ${total_subgraph_realized:.2f}")
print(f"Sum subgraph total_bought: ${total_subgraph_bought:.2f}")

# Wallet cached values
w = Wallet.objects.get(id=wallet_id)
print(f"\nWallet cached: realized_pnl=${w.subgraph_realized_pnl}, total_bought=${w.subgraph_total_bought}")

# PM all-time PnL = $20,172.77
# Our cash flow all-time = $40,776.42
# Difference = -$20,603.65
# Could this be explained by current open positions value being counted differently?

print(f"\n--- Key numbers ---")
pm_all = 20172.77
our_cf_all = 40776.42
print(f"PM all-time PnL: ${pm_all:.2f}")
print(f"Our cash flow PnL: ${our_cf_all:.2f}")
print(f"Difference: ${pm_all - our_cf_all:.2f}")
print(f"Total unrealized in current positions: ${total_unrealized:.2f}")
print(f"Cash flow + unrealized: ${our_cf_all + total_unrealized:.2f}")

# Check: PM vol for all = 773199.66, for month = 39257.10
# Our buy_cost all = 124288.70, sells all = 79828.31 => total traded ~204k
# PM vol is much higher - maybe vol includes both sides? Or is it notional?

# Let's check total trade volume from our DB
buys_all = Trade.objects.filter(wallet_id=wallet_id, side='BUY').aggregate(s=Sum('total_value'))['s'] or 0
sells_all = Trade.objects.filter(wallet_id=wallet_id, side='SELL').aggregate(s=Sum('total_value'))['s'] or 0
buys_size = Trade.objects.filter(wallet_id=wallet_id, side='BUY').aggregate(s=Sum('size'))['s'] or 0
sells_size = Trade.objects.filter(wallet_id=wallet_id, side='SELL').aggregate(s=Sum('size'))['s'] or 0
print(f"\nOur total buy value: ${float(buys_all):.2f}")
print(f"Our total sell value: ${float(sells_all):.2f}")
print(f"Our total buy size (shares): {float(buys_size):.2f}")
print(f"Our total sell size (shares): {float(sells_size):.2f}")
print(f"Buy+Sell value: ${float(buys_all + sells_all):.2f}")
print(f"Buy+Sell size: {float(buys_size + sells_size):.2f}")

# Also check splits and merges
splits = Activity.objects.filter(wallet_id=wallet_id, activity_type='SPLIT').aggregate(s=Sum('usdc_size'))['s'] or 0
merges = Activity.objects.filter(wallet_id=wallet_id, activity_type='MERGE').aggregate(s=Sum('usdc_size'))['s'] or 0
redeems = Activity.objects.filter(wallet_id=wallet_id, activity_type='REDEEM').aggregate(s=Sum('usdc_size'))['s'] or 0
print(f"\nSplits: ${float(splits):.2f}")
print(f"Merges: ${float(merges):.2f}")
print(f"Redeems: ${float(redeems):.2f}")
print(f"Total volume with splits/merges: ${float(buys_all + sells_all) + float(splits) + float(merges):.2f}")

# PM categories don't add up to overall - try summing
print(f"\n--- Category analysis ---")
# weather=$20472.34, sports=$-94.30, politics=$-38.59, crypto=$-102.32
# Sum = $20237.12, but PM overall = $20172.77
# Difference = $64.35
cat_sum = 20472.34 + (-94.30) + (-38.59) + (-102.32)
print(f"Sum of categories: ${cat_sum:.2f}")
print(f"PM overall: $20172.77")
print(f"Diff: ${cat_sum - 20172.77:.2f}")

# Key insight: weather PnL ($20472) > overall PnL ($20173)!
# This suggests overall might have additional categories dragging it down,
# or there's overlap/different calculation

# Now let's try to understand month PnL
# PM month = $710.14, our cash flow month = $4480.95
# The ratio is 0.1585, very different from all-time ratio 0.4947
# This means it's NOT a simple scaling

# Let me check: what if PM month = mark-to-market change over 30 days?
# i.e., (current portfolio value + cash extracted in month) - (portfolio value 30 days ago + cash invested in month)
# This would be: unrealized PnL change + realized PnL in month

# Check positions that have trades in the last 30 days
now = datetime(2026, 2, 16, 8, 0)
month_ago = now - timedelta(days=30)

month_trades = Trade.objects.filter(wallet_id=wallet_id, datetime__gte=month_ago)
print(f"\n--- Month trades ---")
print(f"Trades in last 30d: {month_trades.count()}")
month_buys = month_trades.filter(side='BUY').aggregate(s=Sum('total_value'))['s'] or 0
month_sells = month_trades.filter(side='SELL').aggregate(s=Sum('total_value'))['s'] or 0
print(f"Month buys: ${float(month_buys):.2f}")
print(f"Month sells: ${float(month_sells):.2f}")

# Check: what's the current unrealized for positions traded this month?
month_assets = month_trades.values_list('asset', flat=True).distinct()
month_positions = CurrentPosition.objects.filter(wallet_id=wallet_id, asset__in=month_assets)
month_unrealized = sum(float(p.current_value - p.initial_value) for p in month_positions)
month_pos_realized = sum(float(p.realized_pnl) for p in month_positions)
print(f"Current unrealized for month-traded positions: ${month_unrealized:.2f}")
print(f"Current realized for month-traded positions: ${month_pos_realized:.2f}")

# Let me also check: for positions traded this month, what's cash_pnl?
month_cash_pnl = sum(float(p.cash_pnl) for p in month_positions)
print(f"cash_pnl for month-traded positions: ${month_cash_pnl:.2f}")

# Print individual positions with recent trades
print(f"\nPositions traded this month:")
for p in month_positions[:20]:
    trades_for = month_trades.filter(asset=p.asset)
    buy_v = sum(float(t.total_value) for t in trades_for.filter(side='BUY'))
    sell_v = sum(float(t.total_value) for t in trades_for.filter(side='SELL'))
    print(f"  {p.outcome[:40]:40s} size={float(p.size):>10.2f} cur_price={float(p.cur_price):.4f} "
          f"init_v={float(p.initial_value):>8.2f} cur_v={float(p.current_value):>8.2f} "
          f"cash_pnl={float(p.cash_pnl):>8.2f} realized={float(p.realized_pnl):>8.2f} "
          f"month_buys=${buy_v:.2f} month_sells=${sell_v:.2f}")

print("\nDone!")
