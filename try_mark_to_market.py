"""
Mark-to-market PnL calculator: simulate portfolio from trades + activities.
Goal: replicate Polymarket's ALL-TIME PnL of $20,172.77 for wallet 1pixel (id=7).
"""
import os, sys, django
from decimal import Decimal
from datetime import datetime, timezone as tz
from collections import defaultdict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Trade, Activity, Market

WALLET_ID = 7

# Load all trades
trades = list(Trade.objects.filter(wallet_id=WALLET_ID).values(
    'side', 'price', 'size', 'total_value', 'datetime', 'timestamp',
    'outcome', 'market_id', 'asset', 'transaction_hash'
))

# Load all activities
activities = list(Activity.objects.filter(wallet_id=WALLET_ID).values(
    'activity_type', 'size', 'usdc_size', 'timestamp', 'datetime',
    'outcome', 'market_id', 'asset', 'transaction_hash'
))

print(f"Loaded {len(trades)} trades, {len(activities)} activities")

# Count activity types
from collections import Counter
act_types = Counter(a['activity_type'] for a in activities)
print(f"Activity types: {dict(act_types)}")

# Build unified event list with sortable timestamp
events = []

for t in trades:
    # trades have datetime as DateTimeField
    dt = t['datetime']
    ts = int(dt.timestamp()) if dt else t['timestamp']
    events.append({
        'type': 'TRADE',
        'side': t['side'],
        'price': float(t['price']),
        'size': float(t['size']),
        'total_value': float(t['total_value']),
        'ts': ts,
        'dt': dt,
        'outcome': t['outcome'],
        'market_id': t['market_id'],
        'asset': t['asset'],
        'tx': t['transaction_hash'],
    })

for a in activities:
    ts = a['timestamp']
    events.append({
        'type': a['activity_type'],
        'size': float(a['size']),
        'usdc_size': float(a['usdc_size']),
        'ts': ts,
        'dt': a['datetime'],
        'outcome': a['outcome'],
        'market_id': a['market_id'],
        'asset': a['asset'],
        'tx': a['transaction_hash'],
    })

# Sort by timestamp, then type (activities after trades at same ts)
events.sort(key=lambda e: (e['ts'], 0 if e['type'] == 'TRADE' else 1))

print(f"Total events: {len(events)}")
print(f"Date range: {events[0]['dt']} to {events[-1]['dt']}")

# Simulate portfolio
cash = 0.0  # net cash flow (positive = profit extracted)
# positions[asset] = number of tokens held
positions = defaultdict(float)

# Monthly snapshots
monthly_cash = {}
current_month = None

for e in events:
    dt = e['dt']
    month_key = f"{dt.year}-{dt.month:02d}" if dt else "unknown"
    
    if month_key != current_month:
        if current_month is not None:
            monthly_cash[current_month] = cash
        current_month = month_key

    etype = e['type']
    
    if etype == 'TRADE':
        cost = e['price'] * e['size']  # USDC equivalent
        asset = e['asset']
        if e['side'] == 'BUY':
            cash -= cost
            positions[asset] += e['size']
        else:  # SELL
            cash += cost
            positions[asset] -= e['size']
    
    elif etype == 'SPLIT':
        # Pay USDC, receive YES + NO tokens
        cash -= e['usdc_size']
        # We don't know the exact YES/NO asset IDs from the activity
        # SPLIT gives both outcomes for the market
        # For tracking, we'd need to know both asset IDs
        # For now, just track cash impact
        
    elif etype == 'MERGE':
        # Return YES + NO tokens, receive USDC
        cash += e['usdc_size']
    
    elif etype == 'REDEEM':
        # Return winning tokens, receive USDC
        cash += e['usdc_size']
        # Remove tokens from position
        asset = e['asset']
        if asset:
            positions[asset] -= e['size']
    
    elif etype == 'REWARD':
        cash += e['usdc_size']
    
    elif etype == 'CONVERSION':
        pass  # ignore

# Final month
if current_month:
    monthly_cash[current_month] = cash

print(f"\n=== RESULTS ===")
print(f"Final cash balance: ${cash:,.2f}")

# Count open positions (non-zero)
open_pos = {k: v for k, v in positions.items() if abs(v) > 0.01}
print(f"Open positions: {len(open_pos)}")

# Try to value open positions using last trade price
open_value = 0.0
for asset, qty in sorted(open_pos.items(), key=lambda x: -abs(x[1])):
    # Find last trade for this asset
    last_trade = Trade.objects.filter(
        wallet_id=WALLET_ID, asset=asset
    ).order_by('-timestamp').first()
    
    price = float(last_trade.price) if last_trade else 0
    value = qty * price
    open_value += value
    if abs(qty) > 10:
        market_title = ""
        if last_trade and last_trade.market:
            market_title = last_trade.market.title[:50]
        print(f"  {asset[:12]}.. qty={qty:,.1f} price={price:.4f} val=${value:,.2f} [{market_title}]")

print(f"\nOpen position value: ${open_value:,.2f}")
print(f"PnL = cash + open = ${cash + open_value:,.2f}")
print(f"Target (Polymarket): $20,172.77")
print(f"Difference: ${cash + open_value - 20172.77:,.2f}")

# Monthly PnL (incremental)
print(f"\n=== MONTHLY CASH BALANCE (cumulative) ===")
prev = 0
for month, val in sorted(monthly_cash.items()):
    delta = val - prev
    print(f"  {month}: cumulative=${val:,.2f}  delta=${delta:,.2f}")
    prev = val
