"""PM PnL simulation v3 - infer winners from redeems, snapshot-based monthly."""
import os, sys
from datetime import datetime, timedelta
from decimal import Decimal
from collections import defaultdict

os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
import django; django.setup()
from wallet_analysis.models import Trade, Activity, Market

wallet_id = 7

class Pos:
    __slots__ = ['amount', 'avg_price', 'realized_pnl', 'total_bought']
    def __init__(self):
        self.amount = Decimal(0)
        self.avg_price = Decimal(0)
        self.realized_pnl = Decimal(0)
        self.total_bought = Decimal(0)
    def buy(self, price, amount):
        if amount <= 0: return
        denom = self.amount + amount
        if denom > 0:
            self.avg_price = (self.avg_price * self.amount + price * amount) / denom
        self.amount += amount
        self.total_bought += amount
    def sell(self, price, amount):
        if amount <= 0: return
        adj = min(amount, self.amount)
        if adj <= 0: return
        self.realized_pnl += adj * (price - self.avg_price)
        self.amount -= adj

# Build market -> {outcome: asset} from trades
print("Building maps...")
market_assets = defaultdict(dict)
for row in Trade.objects.filter(wallet_id=wallet_id).values('market_id', 'asset', 'outcome').distinct():
    market_assets[row['market_id']][row['outcome']] = row['asset']

# Get resolution data
market_winners = {}
for m in Market.objects.filter(resolved=True).exclude(winning_outcome=''):
    market_winners[m.id] = m.winning_outcome

print(f"Markets: {len(market_assets)}, resolved(DB): {len(market_winners)}")

def build_all_events():
    """Get all events sorted by timestamp."""
    events = []
    for t in Trade.objects.filter(wallet_id=wallet_id).order_by('timestamp', 'id'):
        events.append({
            'ts': t.timestamp, 'sort': 0, 'id': t.id,
            'type': 'trade', 'side': t.side, 'asset': t.asset,
            'price': t.price, 'size': t.size, 'market_id': t.market_id,
            'outcome': t.outcome, 'dt': t.datetime,
        })
    for a in Activity.objects.filter(wallet_id=wallet_id).order_by('timestamp', 'id'):
        events.append({
            'ts': a.timestamp, 'sort': 1, 'id': a.id,
            'type': a.activity_type, 'asset': a.asset,
            'size': a.size, 'usdc_size': a.usdc_size,
            'market_id': a.market_id, 'outcome': a.outcome, 'dt': a.datetime,
        })
    events.sort(key=lambda x: (x['ts'], x['sort'], x['id']))
    return events

def simulate(events, cutoff_dt=None):
    """Run simulation up to cutoff_dt (None = all). Returns total realized PnL."""
    positions = {}
    
    for e in events:
        if cutoff_dt and e['dt'] and e['dt'] >= cutoff_dt:
            break
        
        etype = e['type']
        
        if etype == 'trade':
            asset = e['asset']
            if asset not in positions: positions[asset] = Pos()
            if e['side'] == 'BUY':
                positions[asset].buy(e['price'], e['size'])
            else:
                positions[asset].sell(e['price'], e['size'])
        
        elif etype == 'SPLIT':
            mid = e['market_id']
            assets = market_assets.get(mid, {})
            if len(assets) >= 2:
                for out, aid in assets.items():
                    if aid not in positions: positions[aid] = Pos()
                    positions[aid].buy(Decimal('0.5'), e['size'])
        
        elif etype == 'MERGE':
            mid = e['market_id']
            assets = market_assets.get(mid, {})
            if len(assets) >= 2:
                for out, aid in assets.items():
                    if aid not in positions: positions[aid] = Pos()
                    positions[aid].sell(Decimal('0.5'), e['size'])
        
        elif etype == 'REDEEM':
            mid = e['market_id']
            assets = market_assets.get(mid, {})
            winner = market_winners.get(mid)
            
            if not assets:
                continue
            
            if not winner and len(assets) >= 2:
                # Infer winner: the outcome where user has shares matching usdc_size
                best_match = None
                best_diff = Decimal('999999')
                for out, aid in assets.items():
                    pos = positions.get(aid)
                    if pos and pos.amount > 0:
                        diff = abs(pos.amount - e['usdc_size'])
                        if diff < best_diff:
                            best_diff = diff
                            best_match = out
                if best_match:
                    winner = best_match
            
            if not winner:
                # Last resort: if only one outcome has shares, that's the winner
                outcomes_with_shares = [(out, aid) for out, aid in assets.items() 
                                       if positions.get(aid) and positions[aid].amount > 0]
                if len(outcomes_with_shares) == 1:
                    winner = outcomes_with_shares[0][0]
            
            if winner and len(assets) >= 2:
                for out, aid in assets.items():
                    if aid not in positions: positions[aid] = Pos()
                    pos = positions[aid]
                    if out == winner:
                        pos.sell(Decimal('1.0'), pos.amount)
                    else:
                        pos.sell(Decimal('0.0'), pos.amount)
        
        elif etype == 'CONVERSION':
            # neg-risk conversion: treated as merge old + split new
            # Skip for now
            pass
    
    total = sum(float(p.realized_pnl) for p in positions.values())
    return total, positions

print("Loading all events...")
all_events = build_all_events()
print(f"Total events: {len(all_events)}")

# Simulate all-time
print("\n=== ALL-TIME PnL ===")
pnl_all, pos_all = simulate(all_events)
print(f"Simulated: ${pnl_all:.2f}  PM: $20172.77  diff: ${pnl_all - 20172.77:.2f}")

# SNAPSHOT-BASED MONTHLY: monthly = all_now - all_30days_ago
from django.utils import timezone
now = datetime(2026, 2, 16, 8, 0, tzinfo=timezone.utc)
month_ago = now - timedelta(days=30)
week_ago = now - timedelta(days=7)
day_ago = now - timedelta(days=1)

print("\n=== SNAPSHOT-BASED PERIOD PnL ===")
pnl_month_ago, _ = simulate(all_events, cutoff_dt=month_ago)
pnl_week_ago, _ = simulate(all_events, cutoff_dt=week_ago)
pnl_day_ago, _ = simulate(all_events, cutoff_dt=day_ago)

month_pnl = pnl_all - pnl_month_ago
week_pnl = pnl_all - pnl_week_ago
day_pnl = pnl_all - pnl_day_ago

print(f"Month: sim=${month_pnl:>10.2f}  PM=$710.14  diff=${month_pnl - 710.14:.2f}")
print(f"Week:  sim=${week_pnl:>10.2f}  PM=$0.04    diff=${week_pnl - 0.04:.2f}")
print(f"Day:   sim=${day_pnl:>10.2f}  PM=$0.04    diff=${day_pnl - 0.04:.2f}")

print(f"\nAll-time at month_ago: ${pnl_month_ago:.2f}")
print(f"All-time at week_ago:  ${pnl_week_ago:.2f}")
print(f"All-time at day_ago:   ${pnl_day_ago:.2f}")
print(f"All-time now:          ${pnl_all:.2f}")

# Check open positions value
open_count = sum(1 for p in pos_all.values() if p.amount > 0)
open_value = sum(float(p.amount) for p in pos_all.values() if p.amount > 0)
print(f"\nOpen positions: {open_count}, total shares: {open_value:.2f}")

# Show top unrealized
open_pos = [(a, p) for a, p in pos_all.items() if p.amount > Decimal('1')]
open_pos.sort(key=lambda x: float(x[1].amount), reverse=True)
print("Top open positions by amount:")
for asset, pos in open_pos[:10]:
    print(f"  {asset[:25]:25s} shares={float(pos.amount):>10.2f} avg={float(pos.avg_price):.4f} rpnl=${float(pos.realized_pnl):>8.2f}")

print("\nDone!")
