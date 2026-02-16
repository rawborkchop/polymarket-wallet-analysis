"""PM PnL simulation v4 - single pass with checkpoints."""
import os
from datetime import datetime, timedelta
from decimal import Decimal
from collections import defaultdict

os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
import django; django.setup()
from wallet_analysis.models import Trade, Activity, Market
from django.utils import timezone

wallet_id = 7

class Pos:
    __slots__ = ['amount', 'avg_price', 'realized_pnl']
    def __init__(self):
        self.amount = Decimal(0)
        self.avg_price = Decimal(0)
        self.realized_pnl = Decimal(0)
    def buy(self, price, amount):
        if amount <= 0: return
        d = self.amount + amount
        if d > 0: self.avg_price = (self.avg_price * self.amount + price * amount) / d
        self.amount += amount
    def sell(self, price, amount):
        if amount <= 0: return
        a = min(amount, self.amount)
        if a <= 0: return
        self.realized_pnl += a * (price - self.avg_price)
        self.amount -= a

# Build maps
market_assets = defaultdict(dict)
for r in Trade.objects.filter(wallet_id=wallet_id).values('market_id', 'asset', 'outcome').distinct():
    market_assets[r['market_id']][r['outcome']] = r['asset']
market_winners = {}
for m in Market.objects.filter(resolved=True).exclude(winning_outcome=''):
    market_winners[m.id] = m.winning_outcome

# Load all events
events = []
for t in Trade.objects.filter(wallet_id=wallet_id).order_by('timestamp', 'id'):
    events.append((t.timestamp, 0, t.id, 'trade', t.side, t.asset, t.price, t.size, t.market_id, t.outcome, t.datetime))
for a in Activity.objects.filter(wallet_id=wallet_id).order_by('timestamp', 'id'):
    events.append((a.timestamp, 1, a.id, a.activity_type, '', a.asset, Decimal(0), a.size, a.market_id, a.outcome, a.datetime))
# Add usdc_size for activities
activity_usdc = {}
for a in Activity.objects.filter(wallet_id=wallet_id):
    activity_usdc[a.id] = a.usdc_size
events.sort()
print(f"Events: {len(events)}")

now = datetime(2026, 2, 16, 8, 0, tzinfo=timezone.UTC)
checkpoints = {
    'month_ago': now - timedelta(days=30),
    'week_ago': now - timedelta(days=7),
    'day_ago': now - timedelta(days=1),
}
checkpoint_pnl = {}
positions = {}

def total_pnl():
    return sum(float(p.realized_pnl) for p in positions.values())

skip_counts = defaultdict(int)

for ev in events:
    ts, sort_key, eid, etype, side, asset, price, size, mid, outcome, dt = ev
    
    # Check checkpoints
    for cp_name, cp_dt in list(checkpoints.items()):
        if dt and dt >= cp_dt:
            checkpoint_pnl[cp_name] = total_pnl()
            del checkpoints[cp_name]
    
    if etype == 'trade':
        if asset not in positions: positions[asset] = Pos()
        if side == 'BUY': positions[asset].buy(price, size)
        else: positions[asset].sell(price, size)
    
    elif etype == 'SPLIT':
        assets = market_assets.get(mid, {})
        if len(assets) >= 2:
            for o, a in assets.items():
                if a not in positions: positions[a] = Pos()
                positions[a].buy(Decimal('0.5'), size)
        else: skip_counts['split'] += 1
    
    elif etype == 'MERGE':
        assets = market_assets.get(mid, {})
        if len(assets) >= 2:
            for o, a in assets.items():
                if a not in positions: positions[a] = Pos()
                positions[a].sell(Decimal('0.5'), size)
        else: skip_counts['merge'] += 1
    
    elif etype == 'REDEEM':
        assets = market_assets.get(mid, {})
        winner = market_winners.get(mid)
        usdc = activity_usdc.get(eid, Decimal(0))
        
        if not assets or len(assets) < 2:
            skip_counts['redeem_no_assets'] += 1
            continue
        
        if not winner:
            # Infer: outcome with shares closest to usdc_size is winner
            best, best_diff = None, Decimal('999999')
            for o, a in assets.items():
                p = positions.get(a)
                if p and p.amount > 0:
                    d = abs(p.amount - usdc)
                    if d < best_diff: best_diff, best = d, o
            if best: winner = best
        
        if not winner:
            # Only one outcome has shares
            with_shares = [(o, a) for o, a in assets.items() if positions.get(a) and positions[a].amount > 0]
            if len(with_shares) == 1: winner = with_shares[0][0]
        
        if winner:
            for o, a in assets.items():
                if a not in positions: positions[a] = Pos()
                p = positions[a]
                if o == winner: p.sell(Decimal('1.0'), p.amount)
                else: p.sell(Decimal('0.0'), p.amount)
        else:
            skip_counts['redeem_no_winner'] += 1

# Remaining checkpoints
for cp_name in list(checkpoints.keys()):
    checkpoint_pnl[cp_name] = total_pnl()

final_pnl = total_pnl()

print(f"\nSkips: {dict(skip_counts)}")
print(f"\n{'='*60}")
print(f"ALL-TIME:  sim=${final_pnl:>12.2f}  PM=$20172.77  diff=${final_pnl-20172.77:>8.2f}")

for period, pm_val, cp in [('MONTH', 710.14, 'month_ago'), ('WEEK', 0.04, 'week_ago'), ('DAY', 0.04, 'day_ago')]:
    cp_pnl = checkpoint_pnl.get(cp, final_pnl)
    period_pnl = final_pnl - cp_pnl
    print(f"{period:>8}:  sim=${period_pnl:>12.2f}  PM=${pm_val:>8.2f}  diff=${period_pnl-pm_val:>8.2f}  (checkpoint=${cp_pnl:.2f})")

# Check: how much PnL comes from conversions we're ignoring?
conv_count = Activity.objects.filter(wallet_id=wallet_id, activity_type='CONVERSION').count()
conv_val = sum(float(a.usdc_size) for a in Activity.objects.filter(wallet_id=wallet_id, activity_type='CONVERSION'))
print(f"\nConversions (ignored): count={conv_count}, total_usdc=${conv_val:.2f}")

# Open positions
open_p = [(a, p) for a, p in positions.items() if p.amount > 1]
open_p.sort(key=lambda x: float(x[1].amount), reverse=True)
print(f"\nOpen positions (>1 share): {len(open_p)}")
for a, p in open_p[:5]:
    print(f"  {a[:25]:25s} shares={float(p.amount):>10.2f} avg={float(p.avg_price):.4f}")

print("\nDone!")
