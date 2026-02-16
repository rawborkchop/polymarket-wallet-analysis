"""Replicate PM's PnL calculation using their subgraph formula.

PM PnL formula (from open source pnl-subgraph):
- Per position, track: amount, avgPrice, realizedPnl, totalBought
- BUY: avgPrice = (avgPrice * amount + buyPrice * buyAmount) / (amount + buyAmount)
        amount += buyAmount; totalBought += buyAmount
- SELL: realizedPnl += min(sellAmount, amount) * (sellPrice - avgPrice) / COLLATERAL_SCALE
        amount -= min(sellAmount, amount)
- SPLIT: buy both Yes+No at 50 cents
- MERGE: sell both Yes+No at 50 cents
- REDEEM: sell at payout price (1.0 for winner, 0.0 for loser)

Total PnL = sum of realizedPnl across all positions
"""
import os, sys
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from collections import defaultdict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
import django
django.setup()

from wallet_analysis.models import Trade, Activity, Market
from django.db.models import Q

wallet_id = 7
SCALE = Decimal('1000000')  # 6 decimal places for USDC

# Build position tracker
class Position:
    def __init__(self):
        self.amount = Decimal(0)  # shares held
        self.avg_price = Decimal(0)  # avg cost in price units
        self.realized_pnl = Decimal(0)  # cumulative realized PnL
        self.total_bought = Decimal(0)  # cumulative shares bought
    
    def buy(self, price, amount):
        if amount <= 0:
            return
        # Update avg price: weighted average
        if self.amount + amount > 0:
            self.avg_price = (self.avg_price * self.amount + price * amount) / (self.amount + amount)
        self.amount += amount
        self.total_bought += amount
    
    def sell(self, price, amount):
        if amount <= 0:
            return
        adjusted = min(amount, self.amount)
        if adjusted <= 0:
            return
        # realized PnL delta
        delta = adjusted * (price - self.avg_price)
        self.realized_pnl += delta
        self.amount -= adjusted

def simulate_pnl(since_dt=None):
    """Simulate PM's PnL calculation."""
    positions = {}  # asset -> Position
    
    # Get all trades and activities, ordered by timestamp
    trade_qs = Trade.objects.filter(wallet_id=wallet_id).order_by('timestamp', 'id')
    activity_qs = Activity.objects.filter(wallet_id=wallet_id).order_by('timestamp', 'id')
    
    if since_dt:
        trade_qs = trade_qs.filter(datetime__gte=since_dt)
        activity_qs = activity_qs.filter(datetime__gte=since_dt)
    
    # Combine into a single timeline
    events = []
    for t in trade_qs:
        events.append({
            'ts': t.timestamp, 'type': 'trade', 'side': t.side,
            'asset': t.asset, 'price': t.price, 'size': t.size,
            'total_value': t.total_value, 'market_id': t.market_id,
            'outcome': t.outcome,
        })
    for a in activity_qs:
        events.append({
            'ts': a.timestamp, 'type': a.activity_type,
            'asset': a.asset, 'size': a.size, 'usdc_size': a.usdc_size,
            'market_id': a.market_id, 'outcome': a.outcome,
        })
    
    events.sort(key=lambda x: (x['ts'],))
    
    for e in events:
        etype = e['type']
        
        if etype == 'trade':
            asset = e['asset']
            if asset not in positions:
                positions[asset] = Position()
            pos = positions[asset]
            
            if e['side'] == 'BUY':
                pos.buy(e['price'], e['size'])
            else:  # SELL
                pos.sell(e['price'], e['size'])
        
        elif etype == 'SPLIT':
            # Split: buy both Yes+No at $0.50 for `size` shares each
            # We need to find which market this is for and get both assets
            market_id = e.get('market_id')
            if market_id:
                # Find the complementary outcomes for this market
                # For splits, we buy both outcomes at 0.50
                # The activity gives us one asset, but split affects both
                asset = e['asset']
                if asset not in positions:
                    positions[asset] = Position()
                # Split buys at 50 cents
                positions[asset].buy(Decimal('0.5'), e['size'])
                
                # Find complement asset - look for other trades in same market
                complement = _find_complement(asset, market_id)
                if complement:
                    if complement not in positions:
                        positions[complement] = Position()
                    positions[complement].buy(Decimal('0.5'), e['size'])
            
        elif etype == 'MERGE':
            market_id = e.get('market_id')
            asset = e['asset']
            if asset not in positions:
                positions[asset] = Position()
            positions[asset].sell(Decimal('0.5'), e['size'])
            
            if market_id:
                complement = _find_complement(asset, market_id)
                if complement:
                    if complement not in positions:
                        positions[complement] = Position()
                    positions[complement].sell(Decimal('0.5'), e['size'])
        
        elif etype == 'REDEEM':
            # Redeem: sell at payout price
            # Winner outcome gets price=1.0, loser gets price=0.0
            asset = e['asset']
            if asset not in positions:
                positions[asset] = Position()
            
            # Determine if this is winning or losing outcome
            market_id = e.get('market_id')
            payout_price = _get_payout_price(asset, market_id, e.get('outcome', ''))
            positions[asset].sell(payout_price, positions[asset].amount)
    
    total_pnl = sum(p.realized_pnl for p in positions.values())
    return float(total_pnl), positions

# Helper caches
_complement_cache = {}
def _find_complement(asset, market_id):
    key = (asset, market_id)
    if key in _complement_cache:
        return _complement_cache[key]
    # Find other assets traded in the same market
    other_assets = Trade.objects.filter(
        wallet_id=wallet_id, market_id=market_id
    ).exclude(asset=asset).values_list('asset', flat=True).distinct()[:1]
    
    if not other_assets:
        other_assets = Activity.objects.filter(
            wallet_id=wallet_id, market_id=market_id
        ).exclude(asset=asset).values_list('asset', flat=True).distinct()[:1]
    
    result = other_assets[0] if other_assets else None
    _complement_cache[key] = result
    return result

_payout_cache = {}
def _get_payout_price(asset, market_id, outcome):
    if market_id in _payout_cache:
        return _payout_cache.get((market_id, outcome), Decimal('0.5'))
    
    try:
        market = Market.objects.get(id=market_id)
        if market.resolved and market.winning_outcome:
            _payout_cache[(market_id, market.winning_outcome)] = Decimal('1.0')
            # Find the losing outcome
            other_outcomes = Trade.objects.filter(
                wallet_id=wallet_id, market_id=market_id
            ).exclude(outcome=market.winning_outcome).values_list('outcome', flat=True).distinct()
            for o in other_outcomes:
                _payout_cache[(market_id, o)] = Decimal('0.0')
            return _payout_cache.get((market_id, outcome), Decimal('0.5'))
    except:
        pass
    return Decimal('1.0')  # Default: assume winner if redeeming

# Run simulations
print("=" * 80)
print("PM PnL SIMULATION (using subgraph formula)")
print("=" * 80)

now = datetime(2026, 2, 16, 8, 0)
periods = {
    'all': None,
    'month': now - timedelta(days=30),
    'week': now - timedelta(days=7),
    'day': now - timedelta(days=1),
}

pm_values = {'all': 20172.77, 'month': 710.14, 'week': 0.04, 'day': 0.04}

for period_name, since in periods.items():
    pnl, positions = simulate_pnl(since)
    pm_val = pm_values[period_name]
    diff = pnl - pm_val
    ratio = pnl / pm_val if pm_val != 0 else float('inf')
    print(f"\n{period_name:>6}: Our sim PnL = ${pnl:>12.2f}  PM PnL = ${pm_val:>12.2f}  Diff = ${diff:>10.2f}  Ratio = {ratio:.4f}")
    
    if period_name == 'all':
        # Show top positions by realized PnL
        sorted_pos = sorted(positions.items(), key=lambda x: abs(float(x[1].realized_pnl)), reverse=True)
        print(f"  Top positions by |realizedPnl| (total {len(positions)} positions):")
        for asset, pos in sorted_pos[:10]:
            print(f"    {asset[:20]:20s} realized=${float(pos.realized_pnl):>10.2f}  amount={float(pos.amount):>10.2f}  avgPrice={float(pos.avg_price):.4f}")

print("\nDone!")
