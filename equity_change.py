"""
Refined analysis - try multiple hypotheses to match PM's $710.14.
Current best: matched trades-only = $1,409.20 (exactly 2x PM's number).
"""
import sys, os, django
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from datetime import datetime, timezone as tz, timedelta
from decimal import Decimal
from collections import defaultdict, deque
from wallet_analysis.models import Trade, Activity

WALLET_ID = 7
ZERO = Decimal('0')

trades = list(Trade.objects.filter(wallet_id=WALLET_ID).order_by('timestamp'))
activities = list(Activity.objects.filter(wallet_id=WALLET_ID).order_by('timestamp'))

market_outcomes = defaultdict(set)
for t in trades:
    if t.market_id and t.outcome:
        market_outcomes[t.market_id].add(t.outcome)

events = []
for t in trades:
    events.append({
        'type': t.side, 'ts': t.timestamp, 'dt': t.datetime,
        'mid': t.market_id, 'outcome': t.outcome,
        'size': t.size, 'price': t.price,
    })
for a in activities:
    events.append({
        'type': a.activity_type, 'ts': a.timestamp, 'dt': a.datetime,
        'mid': a.market_id, 'size': a.size, 'usdc': a.usdc_size, 'outcome': a.outcome,
    })
events.sort(key=lambda e: (e['ts'], 0 if e['type'] in ('SPLIT','MERGE','CONVERSION') else 1))

def compute_matched_trades_pnl(start, end, only_period_buys=False):
    """
    Compute FIFO matched trades-only PnL.
    If only_period_buys=True, only match sells with buys from within the period.
    """
    buy_queues = defaultdict(deque)
    period_pnl = ZERO
    
    for e in events:
        in_period = start <= e['dt'] <= end
        etype = e['type']
        mid = e.get('mid')
        
        if etype == 'BUY':
            if only_period_buys:
                if in_period:
                    buy_queues[(mid, e['outcome'])].append([e['size'], e['price']])
            else:
                buy_queues[(mid, e['outcome'])].append([e['size'], e['price']])
        
        elif etype in ('SPLIT', 'CONVERSION'):
            if not only_period_buys or in_period:
                outcomes = market_outcomes.get(mid, set()) or {'Yes', 'No'}
                n = len(outcomes)
                price_per = (e['usdc'] / n / e['size']) if (e['size'] > 0 and n > 0) else ZERO
                for o in outcomes:
                    buy_queues[(mid, o)].append([e['size'], price_per])
        
        elif etype == 'SELL':
            key = (mid, e['outcome'])
            remaining = e['size']
            cost_basis = ZERO
            matched_size = ZERO
            while remaining > ZERO and buy_queues[key]:
                lot = buy_queues[key][0]
                used = min(remaining, lot[0])
                cost_basis += used * lot[1]
                matched_size += used
                remaining -= used
                lot[0] -= used
                if lot[0] <= ZERO:
                    buy_queues[key].popleft()
            # unmatched: PnL = 0
            if in_period and matched_size > ZERO:
                revenue = e['price'] * matched_size
                period_pnl += revenue - cost_basis
        
        elif etype == 'MERGE':
            outcomes = market_outcomes.get(mid, set())
            total_cost = ZERO
            for o in outcomes:
                key = (mid, o)
                remaining = e['size']
                while remaining > ZERO and buy_queues[key]:
                    lot = buy_queues[key][0]
                    used = min(remaining, lot[0])
                    total_cost += used * lot[1]
                    remaining -= used
                    lot[0] -= used
                    if lot[0] <= ZERO:
                        buy_queues[key].popleft()
            if in_period:
                period_pnl += e['usdc'] - total_cost
    
    return period_pnl

# Test multiple date ranges and hypotheses
print(f"{'Description':<55} {'PnL':>10} {'Diff':>10}")
print("-" * 77)

ranges = [
    ("Jan 16 - Feb 15 (original)", datetime(2026,1,16,tzinfo=tz.utc), datetime(2026,2,15,23,59,59,tzinfo=tz.utc)),
    ("Jan 17 - Feb 16 (shifted +1)", datetime(2026,1,17,tzinfo=tz.utc), datetime(2026,2,16,23,59,59,tzinfo=tz.utc)),
    ("Jan 16 - Feb 14 (30 days)", datetime(2026,1,16,tzinfo=tz.utc), datetime(2026,2,14,23,59,59,tzinfo=tz.utc)),
    ("Jan 15 - Feb 14 (shifted -1)", datetime(2026,1,15,tzinfo=tz.utc), datetime(2026,2,14,23,59,59,tzinfo=tz.utc)),
]

for desc, start, end in ranges:
    pnl = compute_matched_trades_pnl(start, end)
    diff = pnl - Decimal('710.14')
    print(f"{desc:<55} ${pnl:>8,.2f} ${diff:>8,.2f}")

print()

# Test: only buys within period
for desc, start, end in ranges[:1]:
    pnl = compute_matched_trades_pnl(start, end, only_period_buys=True)
    diff = pnl - Decimal('710.14')
    print(f"{'Only period buys: ' + desc:<55} ${pnl:>8,.2f} ${diff:>8,.2f}")

# Test: divide by 2
print()
for desc, start, end in ranges[:2]:
    pnl = compute_matched_trades_pnl(start, end)
    half = pnl / 2
    diff = half - Decimal('710.14')
    print(f"{'HALF of: ' + desc:<55} ${half:>8,.2f} ${diff:>8,.2f}")

# Test: sells only (no merges)
print()
def compute_sells_only(start, end):
    buy_queues = defaultdict(deque)
    period_pnl = ZERO
    for e in events:
        in_period = start <= e['dt'] <= end
        etype = e['type']
        mid = e.get('mid')
        if etype == 'BUY':
            buy_queues[(mid, e['outcome'])].append([e['size'], e['price']])
        elif etype in ('SPLIT', 'CONVERSION'):
            outcomes = market_outcomes.get(mid, set()) or {'Yes', 'No'}
            n = len(outcomes)
            pp = (e['usdc'] / n / e['size']) if (e['size'] > 0 and n > 0) else ZERO
            for o in outcomes:
                buy_queues[(mid, o)].append([e['size'], pp])
        elif etype == 'SELL':
            key = (mid, e['outcome'])
            remaining = e['size']
            cost_basis = ZERO
            ms = ZERO
            while remaining > ZERO and buy_queues[key]:
                lot = buy_queues[key][0]
                used = min(remaining, lot[0])
                cost_basis += used * lot[1]
                ms += used
                remaining -= used
                lot[0] -= used
                if lot[0] <= ZERO:
                    buy_queues[key].popleft()
            if in_period and ms > ZERO:
                period_pnl += e['price'] * ms - cost_basis
        # Skip MERGE
    return period_pnl

for desc, start, end in ranges[:2]:
    pnl = compute_sells_only(start, end)
    diff = pnl - Decimal('710.14')
    print(f"{'Sells only (no merge): ' + desc:<55} ${pnl:>8,.2f} ${diff:>8,.2f}")

# Test: what about including redeems with cost-basis?
print()
def compute_with_redeems(start, end):
    buy_queues = defaultdict(deque)
    period_pnl = ZERO
    for e in events:
        in_period = start <= e['dt'] <= end
        etype = e['type']
        mid = e.get('mid')
        if etype == 'BUY':
            buy_queues[(mid, e['outcome'])].append([e['size'], e['price']])
        elif etype in ('SPLIT', 'CONVERSION'):
            outcomes = market_outcomes.get(mid, set()) or {'Yes', 'No'}
            n = len(outcomes)
            pp = (e['usdc'] / n / e['size']) if (e['size'] > 0 and n > 0) else ZERO
            for o in outcomes:
                buy_queues[(mid, o)].append([e['size'], pp])
        elif etype == 'SELL':
            key = (mid, e['outcome'])
            remaining = e['size']
            cost_basis = ZERO
            ms = ZERO
            while remaining > ZERO and buy_queues[key]:
                lot = buy_queues[key][0]
                used = min(remaining, lot[0])
                cost_basis += used * lot[1]
                ms += used
                remaining -= used
                lot[0] -= used
                if lot[0] <= ZERO:
                    buy_queues[key].popleft()
            if in_period and ms > ZERO:
                period_pnl += e['price'] * ms - cost_basis
        elif etype == 'REDEEM':
            usdc = e.get('usdc', ZERO)
            outcomes = market_outcomes.get(mid, set())
            target = None
            if usdc > ZERO:
                best = (ZERO, None)
                for o in outcomes:
                    q = sum(l[0] for l in buy_queues[(mid, o)])
                    if q > best[0]:
                        best = (q, o)
                target = best[1]
            if target:
                key = (mid, target)
                remaining = e['size']
                cost_basis = ZERO
                ms = ZERO
                while remaining > ZERO and buy_queues[key]:
                    lot = buy_queues[key][0]
                    used = min(remaining, lot[0])
                    cost_basis += used * lot[1]
                    ms += used
                    remaining -= used
                    lot[0] -= used
                    if lot[0] <= ZERO:
                        buy_queues[key].popleft()
                if in_period and ms > ZERO:
                    period_pnl += usdc * (ms / e['size']) - cost_basis
        elif etype == 'MERGE':
            outcomes = market_outcomes.get(mid, set())
            total_cost = ZERO
            for o in outcomes:
                key = (mid, o)
                remaining = e['size']
                while remaining > ZERO and buy_queues[key]:
                    lot = buy_queues[key][0]
                    used = min(remaining, lot[0])
                    total_cost += used * lot[1]
                    remaining -= used
                    lot[0] -= used
                    if lot[0] <= ZERO:
                        buy_queues[key].popleft()
            if in_period:
                period_pnl += e['usdc'] - total_cost
    return period_pnl

for desc, start, end in ranges[:2]:
    pnl = compute_with_redeems(start, end)
    diff = pnl - Decimal('710.14')
    print(f"{'With redeems: ' + desc:<55} ${pnl:>8,.2f} ${diff:>8,.2f}")
