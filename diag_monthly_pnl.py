"""
Diagnostic: Compare monthly PnL approaches vs Polymarket's official monthly figure.
Builds full position history, then:
  1) Sums realized PnL from trades/redeems in last 30 days only
  2) Snapshot difference: all-time PnL now - all-time PnL 30 days ago
  3) Compares both to PM's official monthly PnL from leaderboard API
"""
import django, os, time, requests
from decimal import Decimal
from collections import defaultdict
from dataclasses import dataclass, field

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity

WALLET_ID = 7
D = lambda x: Decimal(str(x))
ZERO = Decimal('0')
ONE = Decimal('1')
EPS = Decimal('0.000001')

# Fetch official monthly PnL
WALLET_ADDR = '0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c'
API_URL = f'https://data-api.polymarket.com/v1/leaderboard?timePeriod=month&user={WALLET_ADDR}'

print("Fetching official monthly PnL from Polymarket API...")
resp = requests.get(API_URL, timeout=10)
data = resp.json()
official_monthly = D(str(data[0]['pnl']))
print(f"Official monthly PnL: ${official_monthly:,.2f}")

# Also get all-time
resp2 = requests.get(f'https://data-api.polymarket.com/v1/leaderboard?timePeriod=all&user={WALLET_ADDR}', timeout=10)
data2 = resp2.json()
official_alltime = D(str(data2[0]['pnl']))
print(f"Official all-time PnL: ${official_alltime:,.2f}")

# Time boundaries
NOW = int(time.time())
THIRTY_DAYS_AGO = NOW - 30 * 86400
print(f"\nNow: {NOW}, 30 days ago: {THIRTY_DAYS_AGO}")
print(f"Window: {time.strftime('%Y-%m-%d %H:%M', time.gmtime(THIRTY_DAYS_AGO))} -> {time.strftime('%Y-%m-%d %H:%M', time.gmtime(NOW))}")


@dataclass
class Pos:
    shares: Decimal = ZERO
    avg_cost: Decimal = ZERO
    realized_pnl: Decimal = ZERO

    def buy(self, size, price):
        old = self.shares * self.avg_cost
        self.shares += size
        if self.shares > EPS:
            self.avg_cost = (old + size * price) / self.shares

    def sell(self, size, price):
        if self.shares > EPS:
            pnl = min(size, self.shares) * (price - self.avg_cost)
            self.realized_pnl += pnl
            self.shares -= size
            if self.shares < EPS:
                self.shares = ZERO
                self.avg_cost = ZERO
        return self.realized_pnl

    def zero_out(self):
        if self.shares > EPS:
            self.realized_pnl -= self.shares * self.avg_cost
            self.shares = ZERO
            self.avg_cost = ZERO


def make_sort_key(etype, obj):
    if etype == 'trade':
        return (obj.timestamp, 0, obj.id)
    else:
        a = obj
        if a.activity_type == 'REDEEM':
            if D(a.usdc_size) > 0:
                return (a.timestamp, 1, a.id)
            else:
                return (a.timestamp, 3, a.id)
        elif a.activity_type in ('SPLIT', 'CONVERSION', 'MERGE'):
            return (a.timestamp, 0, a.id)
        else:
            return (a.timestamp, 2, a.id)


def simulate_with_monthly_tracking(cutoff_ts):
    """
    Run full simulation. Track:
    - Total realized PnL (all-time)
    - Realized PnL snapshot at cutoff_ts
    - Realized PnL from events after cutoff_ts only
    """
    w = Wallet.objects.get(id=WALLET_ID)
    trades = list(Trade.objects.filter(wallet=w).order_by('timestamp', 'id'))
    activities = list(Activity.objects.filter(wallet=w).order_by('timestamp', 'id'))

    events = []
    for t in trades:
        events.append(('trade', t))
    for a in activities:
        if a.activity_type == 'REWARD':
            continue  # skip rewards for trades-only approach
        events.append(('activity', a))

    events.sort(key=lambda x: make_sort_key(x[0], x[1]))

    positions = defaultdict(Pos)
    market_outcomes = defaultdict(set)

    for t in trades:
        if t.market_id:
            market_outcomes[t.market_id].add(t.outcome)

    # Track PnL at cutoff
    pnl_at_cutoff = None
    cutoff_passed = False
    
    # Track per-position PnL at cutoff for "realized in period" method
    pos_pnl_at_cutoff = {}

    for etype, obj in events:
        ts = obj.timestamp
        
        # Snapshot at cutoff
        if not cutoff_passed and ts > cutoff_ts:
            cutoff_passed = True
            pnl_at_cutoff = sum(p.realized_pnl for p in positions.values())
            pos_pnl_at_cutoff = {k: v.realized_pnl for k, v in positions.items()}

        if etype == 'trade':
            t = obj
            if not t.market_id:
                continue
            key = (t.market_id, t.outcome)
            pos = positions[key]
            price, size = D(t.price), D(t.size)
            if t.side == 'BUY':
                pos.buy(size, price)
            else:
                pos.sell(size, price)

        else:
            a = obj
            if not a.market_id:
                continue
            size = D(a.size)
            usdc = D(a.usdc_size)

            if a.activity_type in ('SPLIT', 'CONVERSION'):
                # Skip splits for trades-only approach
                continue

            elif a.activity_type == 'MERGE':
                outcomes = market_outcomes.get(a.market_id, {'Yes', 'No'})
                n = len(outcomes)
                rev_per_share = usdc / (size * n) if size > 0 and n > 0 else ZERO
                for outcome in outcomes:
                    key = (a.market_id, outcome)
                    pos = positions[key]
                    if pos.shares > EPS:
                        pos.sell(min(size, pos.shares), rev_per_share)

            elif a.activity_type == 'REDEEM':
                is_winner = usdc > 0
                if is_winner:
                    market_pos = [(k, v) for k, v in positions.items()
                                  if k[0] == a.market_id and v.shares > EPS]
                    if not market_pos:
                        continue
                    matched = False
                    for key, pos in market_pos:
                        if abs(pos.shares - size) < Decimal('0.5'):
                            pos.sell(size, ONE)
                            matched = True
                            break
                    if not matched:
                        remaining = size
                        for key, pos in sorted(market_pos, key=lambda x: x[1].shares, reverse=True):
                            if pos.shares > EPS and remaining > EPS:
                                amt = min(remaining, pos.shares)
                                pos.sell(amt, ONE)
                                remaining -= amt
                else:
                    for key, pos in positions.items():
                        if key[0] == a.market_id:
                            pos.zero_out()

    # Final totals
    total_pnl_now = sum(p.realized_pnl for p in positions.values())
    
    if pnl_at_cutoff is None:
        # All events are before cutoff
        pnl_at_cutoff = total_pnl_now
        pos_pnl_at_cutoff = {k: v.realized_pnl for k, v in positions.items()}
    
    # Method 1: Snapshot difference
    snapshot_monthly = total_pnl_now - pnl_at_cutoff
    
    # Method 2: Sum of per-position PnL changes since cutoff
    period_realized = ZERO
    for k, pos in positions.items():
        old_pnl = pos_pnl_at_cutoff.get(k, ZERO)
        period_realized += (pos.realized_pnl - old_pnl)

    return {
        'total_pnl_now': total_pnl_now,
        'pnl_at_cutoff': pnl_at_cutoff,
        'snapshot_monthly': snapshot_monthly,
        'period_realized': period_realized,
    }


print("\nRunning simulation...")
result = simulate_with_monthly_tracking(THIRTY_DAYS_AGO)

print(f"\n{'='*70}")
print(f"  MONTHLY PnL COMPARISON (last 30 days)")
print(f"{'='*70}")
print(f"  All-time PnL (our sim):        ${result['total_pnl_now']:>12,.2f}")
print(f"  All-time PnL (PM official):    ${official_alltime:>12,.2f}")
print(f"  All-time gap:                  ${result['total_pnl_now'] - official_alltime:>+12,.2f}")
print(f"")
print(f"  PnL at cutoff (30d ago):       ${result['pnl_at_cutoff']:>12,.2f}")
print(f"")
print(f"  --- Monthly PnL Methods ---")
print(f"  PM official monthly:           ${official_monthly:>12,.2f}")
print(f"  Snapshot diff (now - 30d ago): ${result['snapshot_monthly']:>12,.2f}  (gap: ${result['snapshot_monthly'] - official_monthly:>+.2f})")
print(f"  Period realized PnL:           ${result['period_realized']:>12,.2f}  (gap: ${result['period_realized'] - official_monthly:>+.2f})")
print(f"{'='*70}")

# Extra: check if snapshot diff = period realized (should be identical)
print(f"\n  Snapshot diff == Period realized? {result['snapshot_monthly'] == result['period_realized']}")
print(f"  (Both methods are mathematically equivalent for position-level tracking)")
