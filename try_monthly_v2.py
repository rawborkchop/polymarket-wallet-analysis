"""
Hypothesis: PM monthly PnL = cash flow in period MINUS cost basis of tokens redeemed that were bought before period.

If I redeem $100 worth of tokens this month, but I bought them last month for $80,
the PnL should be $100 - $80 = $20, not $100.

Our cash flow counts the full $100 as income.
"""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from datetime import datetime, date, timedelta
from wallet_analysis.models import Wallet, Trade, Activity
from collections import defaultdict

w = Wallet.objects.get(id=7)

end = date(2026, 2, 15)
start = end - timedelta(days=30)

# Get ALL trades to build cost basis
all_trades = Trade.objects.filter(wallet=w).order_by('datetime')

# Build per-market cost basis using WACB (all time)
# market_id -> {total_bought_qty, total_cost, avg_price}
market_cost = defaultdict(lambda: {'qty': Decimal('0'), 'cost': Decimal('0'), 'avg': Decimal('0')})

for t in all_trades:
    mid = str(t.market_id)
    vol = Decimal(str(t.price)) * Decimal(str(t.size))
    size = Decimal(str(t.size))
    if t.side == 'BUY':
        mc = market_cost[mid]
        mc['cost'] += vol
        mc['qty'] += size
        mc['avg'] = mc['cost'] / mc['qty'] if mc['qty'] > 0 else Decimal('0')

# Now calculate period PnL:
# For trades in period: (sell_price - avg_cost) * size for sells, -(buy_price * size) for buys counted at end
# For redeems in period: (redeem_usdc/size - avg_cost) * size

# Actually simpler: 
# Period PnL = sell_revenue_in_period - buy_cost_in_period + redeem_in_period + merge_in_period - split_in_period
#              - cost_basis_of_redeemed_tokens_bought_BEFORE_period

# Count redeems in period
period_activities = Activity.objects.filter(wallet=w)
period_redeems_total = Decimal('0')
period_redeems_pre_period_cost = Decimal('0')

for a in period_activities:
    ts = datetime.fromtimestamp(int(a.timestamp)).date()
    if start <= ts <= end and a.activity_type == 'REDEEM':
        period_redeems_total += Decimal(str(a.usdc_size or 0))
        # Estimate cost basis of redeemed tokens
        mid = str(a.market_id)
        mc = market_cost.get(mid)
        if mc and mc['qty'] > 0:
            size = Decimal(str(a.size))
            cost_of_redeemed = mc['avg'] * size
            
            # Check how much of this market was bought before vs during period
            bought_before = Decimal('0')
            bought_during = Decimal('0')
            for t in all_trades.filter(market_id=a.market_id, side='BUY'):
                vol = Decimal(str(t.price)) * Decimal(str(t.size))
                if t.datetime.date() < start:
                    bought_before += vol
                else:
                    bought_during += vol
            
            total_bought = bought_before + bought_during
            if total_bought > 0:
                pre_period_ratio = bought_before / total_bought
                period_redeems_pre_period_cost += cost_of_redeemed * pre_period_ratio

# Period trades
period_buy = Decimal('0')
period_sell = Decimal('0')
for t in all_trades:
    if start <= t.datetime.date() <= end:
        vol = Decimal(str(t.price)) * Decimal(str(t.size))
        if t.side == 'BUY':
            period_buy += vol
        else:
            period_sell += vol

# Period activities
period_merge = Decimal('0')
period_split = Decimal('0')
period_reward = Decimal('0')
for a in period_activities:
    ts = datetime.fromtimestamp(int(a.timestamp)).date()
    if start <= ts <= end:
        usdc = Decimal(str(a.usdc_size or 0))
        if a.activity_type == 'MERGE':
            period_merge += usdc
        elif a.activity_type == 'SPLIT':
            period_split += usdc
        elif a.activity_type == 'REWARD':
            period_reward += usdc

# Cash flow PnL
cf = period_sell + period_redeems_total + period_merge + period_reward - period_buy - period_split
# Adjusted PnL (subtract cost basis of pre-period tokens redeemed)
adj = cf - period_redeems_pre_period_cost

print(f"=== PERIOD: {start} to {end} ===")
print(f"Buy cost: ${period_buy:.2f}")
print(f"Sell rev: ${period_sell:.2f}")
print(f"Redeems: ${period_redeems_total:.2f}")
print(f"Merges: ${period_merge:.2f}")
print(f"Splits: ${period_split:.2f}")
print(f"Rewards: ${period_reward:.2f}")
print(f"")
print(f"Cash flow PnL: ${cf:.2f}")
print(f"Pre-period redeem cost basis: ${period_redeems_pre_period_cost:.2f}")
print(f"Adjusted PnL: ${adj:.2f}")
print(f"PM official month: $710.14")
