"""Try mark-to-market PnL for monthly period"""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from datetime import datetime, date, timedelta
from wallet_analysis.models import Wallet, Trade, Activity
from collections import defaultdict

w = Wallet.objects.get(id=7)
trades = list(Trade.objects.filter(wallet=w).order_by('datetime'))
activities = list(Activity.objects.filter(wallet=w).order_by('timestamp'))

# Simulate portfolio over time
# Track: cash balance and token positions
positions = defaultdict(Decimal)  # asset -> quantity
last_price = {}  # asset -> last known price

# Process all events chronologically
all_events = []
for t in trades:
    all_events.append(('trade', t.datetime, t))
for a in activities:
    ts = datetime.fromtimestamp(int(a.timestamp))
    # make timezone-aware to match trades
    import pytz
    ts = ts.replace(tzinfo=pytz.UTC)
    all_events.append(('activity', ts, a))

all_events.sort(key=lambda x: x[1])

# Snapshot dates
end = date(2026, 2, 15)
start_30d = end - timedelta(days=30)

cash = Decimal('0')
snapshots = {}

for etype, dt, obj in all_events:
    d = dt.date()
    
    if etype == 'trade':
        vol = Decimal(str(obj.price)) * Decimal(str(obj.size))
        asset = obj.asset or f"unknown_{obj.market_id}"
        if obj.side == 'BUY':
            cash -= vol
            positions[asset] += Decimal(str(obj.size))
        else:
            cash += vol
            positions[asset] -= Decimal(str(obj.size))
        last_price[asset] = Decimal(str(obj.price))
    else:
        usdc = Decimal(str(obj.usdc_size or 0))
        atype = obj.activity_type
        if atype == 'REDEEM':
            cash += usdc
            # Remove tokens - but we don't know which asset
            # For MTM, this is fine - cash increases, tokens disappear
        elif atype == 'SPLIT':
            cash -= usdc
            # Creates tokens - but we don't track which
        elif atype == 'MERGE':
            cash += usdc
        elif atype == 'REWARD':
            cash += usdc
        elif atype == 'CONVERSION':
            # Token swap - might have cash component
            pass  # try ignoring
    
    # Record daily snapshot
    if d not in snapshots or dt > snapshots[d]['time']:
        # Estimate position value
        pos_value = Decimal('0')
        for asset, qty in positions.items():
            if qty > 0 and asset in last_price:
                pos_value += qty * last_price[asset]
        snapshots[d] = {'time': dt, 'cash': cash, 'pos_value': pos_value, 'equity': cash + pos_value}

# Find snapshots closest to period boundaries
dates = sorted(snapshots.keys())

# Find start of 30d period
start_snap = None
for d in dates:
    if d <= start_30d:
        start_snap = d
    else:
        break

end_snap = None
for d in reversed(dates):
    if d <= end:
        end_snap = d
        break

if start_snap and end_snap:
    s = snapshots[start_snap]
    e = snapshots[end_snap]
    
    print(f"=== MARK-TO-MARKET 30-DAY PnL ===")
    print(f"Start ({start_snap}): cash=${s['cash']:.2f} pos=${s['pos_value']:.2f} equity=${s['equity']:.2f}")
    print(f"End   ({end_snap}): cash=${e['cash']:.2f} pos=${e['pos_value']:.2f} equity=${e['equity']:.2f}")
    print(f"MTM PnL = equity_end - equity_start = ${e['equity'] - s['equity']:.2f}")
    print(f"Cash-only PnL = cash_end - cash_start = ${e['cash'] - s['cash']:.2f}")
    print(f"PM official month: $710.14")

# All time
first_d = dates[0]
last_d = dates[-1]
print(f"\n=== ALL-TIME ===")
print(f"Final cash: ${snapshots[last_d]['cash']:.2f}")
print(f"Final pos value: ${snapshots[last_d]['pos_value']:.2f}")
print(f"Final equity: ${snapshots[last_d]['equity']:.2f}")
print(f"PM official all: $20,172.77")

# Monthly MTM
print(f"\n=== MONTHLY MTM ===")
monthly_dates = {}
for d in dates:
    m = d.strftime('%Y-%m')
    if m not in monthly_dates:
        monthly_dates[m] = {'first': d, 'last': d}
    monthly_dates[m]['last'] = d

prev_equity = Decimal('0')
for m in sorted(monthly_dates.keys()):
    end_eq = snapshots[monthly_dates[m]['last']]['equity']
    mtm = end_eq - prev_equity
    cash_d = snapshots[monthly_dates[m]['last']]['cash'] - (snapshots[monthly_dates[monthly_dates[m]['first'].__class__.__name__ and list(sorted(monthly_dates.keys()))[max(0, list(sorted(monthly_dates.keys())).index(m)-1)]]['last']]['cash'] if m != sorted(monthly_dates.keys())[0] else Decimal('0'))
    print(f"{m}: equity_end=${end_eq:.2f} MTM=${mtm:.2f}")
    prev_equity = end_eq
