"""
PM monthly = (cash + value_of_positions_at_current_prices) at end
           - (cash + value_of_positions_at_current_prices) at start
           
But we need to properly track token balances including redeems.
For redeems, we know the market_id but not the asset. 
However, if usdc_size > 0 it's a winner (tokens -> full value), if 0 it's a loser.
Either way the tokens go to 0 quantity after redeem.
"""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from datetime import datetime, date, timedelta
from wallet_analysis.models import Wallet, Trade, Activity
from collections import defaultdict
import pytz

w = Wallet.objects.get(id=7)

# Build chronological event list
events = []
for t in Trade.objects.filter(wallet=w).order_by('datetime'):
    events.append({
        'type': 'trade', 'dt': t.datetime, 'side': t.side,
        'asset': t.asset, 'market_id': str(t.market_id),
        'size': Decimal(str(t.size)), 'price': Decimal(str(t.price)),
        'usdc': Decimal(str(t.price)) * Decimal(str(t.size))
    })

for a in Activity.objects.filter(wallet=w).order_by('timestamp'):
    ts = datetime.fromtimestamp(int(a.timestamp), tz=pytz.UTC)
    events.append({
        'type': a.activity_type, 'dt': ts, 'market_id': str(a.market_id),
        'size': Decimal(str(a.size)), 'usdc': Decimal(str(a.usdc_size or 0)),
        'asset': a.asset or ''
    })

events.sort(key=lambda x: x['dt'])

# Track positions by market_id (not asset - since redeems don't have asset)
# For each market: track net token balance and cost basis
market_positions = defaultdict(lambda: {'qty': Decimal('0'), 'cost': Decimal('0')})
cash = Decimal('0')
last_price = {}  # market_id -> last trade price

# Snapshot function
def snapshot():
    pos_value = Decimal('0')
    for mid, pos in market_positions.items():
        if pos['qty'] > 0:
            price = last_price.get(mid, Decimal('0.5'))  # default to 0.5 if unknown
            pos_value += pos['qty'] * price
    return cash, pos_value, cash + pos_value

end = date(2026, 2, 15)
start = end - timedelta(days=30)
week_start = end - timedelta(days=7)

snap_start = snap_week = snap_end = None

for ev in events:
    d = ev['dt'].date()
    
    if ev['type'] == 'trade':
        mid = ev['market_id']
        if ev['side'] == 'BUY':
            cash -= ev['usdc']
            market_positions[mid]['qty'] += ev['size']
            market_positions[mid]['cost'] += ev['usdc']
        else:
            cash += ev['usdc']
            market_positions[mid]['qty'] -= ev['size']
        last_price[mid] = ev['price']
    elif ev['type'] == 'REDEEM':
        cash += ev['usdc']
        mid = ev['market_id']
        # Close position for this market
        market_positions[mid]['qty'] = Decimal('0')
        market_positions[mid]['cost'] = Decimal('0')
    elif ev['type'] == 'SPLIT':
        cash -= ev['usdc']
        # Creates tokens in market - but split creates BOTH sides
        # Net effect on position value: spend USDC, get YES+NO tokens worth ~= USDC spent
        mid = ev['market_id']
        market_positions[mid]['qty'] += ev['size']  # simplified
    elif ev['type'] == 'MERGE':
        cash += ev['usdc']
        mid = ev['market_id']
        market_positions[mid]['qty'] -= ev['size']
    elif ev['type'] == 'REWARD':
        cash += ev['usdc']
    
    # Capture snapshots
    if d == start and (snap_start is None or ev['dt'] > snap_start[0]):
        c, pv, eq = snapshot()
        snap_start = (ev['dt'], c, pv, eq)
    if d == week_start and (snap_week is None or ev['dt'] > snap_week[0]):
        c, pv, eq = snapshot()
        snap_week = (ev['dt'], c, pv, eq)

# Final snapshot
c, pv, eq = snapshot()
snap_end = (events[-1]['dt'], c, pv, eq)

print(f"=== MARK-TO-MARKET (tracking by market_id, redeems close positions) ===")
if snap_start:
    print(f"Start ({snap_start[0].date()}): cash=${snap_start[1]:.2f} pos=${snap_start[2]:.2f} eq=${snap_start[3]:.2f}")
print(f"End   ({snap_end[0].date()}): cash=${snap_end[1]:.2f} pos=${snap_end[2]:.2f} eq=${snap_end[3]:.2f}")

if snap_start:
    mtm_month = snap_end[3] - snap_start[3]
    print(f"\nMTM monthly PnL: ${mtm_month:.2f}")
    print(f"PM official month: $710.14")

if snap_week:
    mtm_week = snap_end[3] - snap_week[3]
    print(f"\nMTM weekly PnL: ${mtm_week:.2f}")
    print(f"PM official week: $0.04")

print(f"\nALL-TIME cash: ${snap_end[1]:.2f}")
print(f"PM official all: $20,172.77")
print(f"\nOpen positions: {sum(1 for p in market_positions.values() if p['qty'] > 0)}")
print(f"Position value: ${snap_end[2]:.2f}")
