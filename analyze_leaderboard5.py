"""Fixed PM PnL simulation - look up assets from market trades."""
import os, sys
from datetime import datetime, timedelta
from decimal import Decimal
from collections import defaultdict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
import django; django.setup()

from wallet_analysis.models import Trade, Activity, Market

wallet_id = 7

class Pos:
    def __init__(self):
        self.amount = Decimal(0)
        self.avg_price = Decimal(0)
        self.realized_pnl = Decimal(0)
        self.total_bought = Decimal(0)
    
    def buy(self, price, amount):
        if amount <= 0: return
        if self.amount + amount > 0:
            self.avg_price = (self.avg_price * self.amount + price * amount) / (self.amount + amount)
        self.amount += amount
        self.total_bought += amount
    
    def sell(self, price, amount):
        if amount <= 0: return
        adj = min(amount, self.amount)
        if adj <= 0: return
        self.realized_pnl += adj * (price - self.avg_price)
        self.amount -= adj

# Pre-build market -> assets mapping
print("Building market-assets map...")
from django.db.models import Count
market_assets = {}
# Get all assets per market from trades
trades_by_market = Trade.objects.filter(wallet_id=wallet_id).values('market_id', 'asset', 'outcome').distinct()
for t in trades_by_market:
    mid = t['market_id']
    if mid not in market_assets:
        market_assets[mid] = {}
    market_assets[mid][t['outcome']] = t['asset']

# Also get market resolution data
market_winners = {}
for m in Market.objects.filter(resolved=True).exclude(winning_outcome=''):
    market_winners[m.id] = m.winning_outcome

print(f"Markets with assets: {len(market_assets)}, resolved: {len(market_winners)}")

def simulate_pnl(since_dt=None):
    positions = {}  # asset -> Pos
    
    trade_qs = Trade.objects.filter(wallet_id=wallet_id).order_by('timestamp', 'id')
    activity_qs = Activity.objects.filter(wallet_id=wallet_id).order_by('timestamp', 'id')
    
    if since_dt:
        trade_qs = trade_qs.filter(datetime__gte=since_dt)
        activity_qs = activity_qs.filter(datetime__gte=since_dt)
    
    events = []
    for t in trade_qs:
        events.append(('trade', t.timestamp, t.id, t.side, t.asset, t.price, t.size, t.market_id, t.outcome))
    for a in activity_qs:
        events.append(('activity', a.timestamp, a.id, a.activity_type, a.asset, a.size, a.usdc_size, a.market_id, a.outcome))
    events.sort(key=lambda x: (x[1], x[0], x[2]))
    
    skip_splits = 0
    skip_merges = 0
    skip_redeems = 0
    
    for e in events:
        if e[0] == 'trade':
            _, ts, eid, side, asset, price, size, market_id, outcome = e
            if asset not in positions:
                positions[asset] = Pos()
            if side == 'BUY':
                positions[asset].buy(price, size)
            else:
                positions[asset].sell(price, size)
        
        elif e[0] == 'activity':
            _, ts, eid, atype, asset_field, size, usdc_size, market_id, outcome = e
            
            if atype == 'SPLIT':
                # Buy both outcomes at $0.50
                assets = market_assets.get(market_id, {})
                if len(assets) >= 2:
                    for outcome_name, asset_id in assets.items():
                        if asset_id not in positions:
                            positions[asset_id] = Pos()
                        positions[asset_id].buy(Decimal('0.5'), size)
                else:
                    skip_splits += 1
            
            elif atype == 'MERGE':
                # Sell both outcomes at $0.50
                assets = market_assets.get(market_id, {})
                if len(assets) >= 2:
                    for outcome_name, asset_id in assets.items():
                        if asset_id not in positions:
                            positions[asset_id] = Pos()
                        positions[asset_id].sell(Decimal('0.5'), size)
                else:
                    skip_merges += 1
            
            elif atype == 'REDEEM':
                # Sell winning at 1.0, losing at 0.0
                assets = market_assets.get(market_id, {})
                winner = market_winners.get(market_id)
                if assets and winner:
                    for outcome_name, asset_id in assets.items():
                        if asset_id not in positions:
                            positions[asset_id] = Pos()
                        pos = positions[asset_id]
                        if outcome_name == winner:
                            pos.sell(Decimal('1.0'), pos.amount)
                        else:
                            pos.sell(Decimal('0.0'), pos.amount)
                else:
                    skip_redeems += 1
            
            elif atype == 'CONVERSION':
                # Conversion in neg-risk: similar to merge+split
                # For now, skip
                pass
    
    total_pnl = sum(float(p.realized_pnl) for p in positions.values())
    unrealized = sum(float(p.amount * (Decimal('0.5') - p.avg_price)) for p in positions.values() if p.amount > 0)
    return total_pnl, unrealized, skip_splits, skip_merges, skip_redeems, positions

print("\n" + "=" * 80)
print("PM PnL SIMULATION v2")
print("=" * 80)

now = datetime(2026, 2, 16, 8, 0)
periods = {'all': None, 'month': now - timedelta(days=30), 'week': now - timedelta(days=7), 'day': now - timedelta(days=1)}
pm_values = {'all': 20172.77, 'month': 710.14, 'week': 0.04, 'day': 0.04}

for pname, since in periods.items():
    pnl, unreal, ss, sm, sr, positions = simulate_pnl(since)
    pm = pm_values[pname]
    print(f"\n{pname:>6}: sim=${pnl:>12.2f}  PM=${pm:>12.2f}  diff=${pnl-pm:>10.2f}  ratio={pnl/pm if pm else 0:.4f}")
    print(f"        unrealized(at 0.5)=${unreal:>10.2f}  skip: splits={ss} merges={sm} redeems={sr}")
    
    if pname == 'all':
        # Count open positions
        open_pos = [(a, p) for a, p in positions.items() if p.amount > 0]
        print(f"        open positions: {len(open_pos)}, total positions: {len(positions)}")
        # Top by |realized|
        top = sorted(positions.items(), key=lambda x: abs(float(x[1].realized_pnl)), reverse=True)[:5]
        for asset, pos in top:
            print(f"          {asset[:25]:25s} rpnl=${float(pos.realized_pnl):>10.2f} amt={float(pos.amount):>8.2f} avg={float(pos.avg_price):.4f}")

# Also try: all-time PnL but only counting trades (no splits/merges/redeems)
print("\n\n--- Trades-only PnL (no activities) ---")
positions2 = {}
for t in Trade.objects.filter(wallet_id=wallet_id).order_by('timestamp'):
    if t.asset not in positions2:
        positions2[t.asset] = Pos()
    if t.side == 'BUY':
        positions2[t.asset].buy(t.price, t.size)
    else:
        positions2[t.asset].sell(t.price, t.size)
trades_pnl = sum(float(p.realized_pnl) for p in positions2.values())
print(f"Trades-only realized PnL: ${trades_pnl:.2f}")

print("\nDone!")
