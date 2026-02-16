"""Analysis 9: Check if open positions make sense.
653k open shares at $441k cost. Most should be neg-risk "No" tokens at ~$0.99.
If these resolve at $1, that's $653k revenue = PnL of +$212k.
If PM values them at current price, PnL = realized + unrealized.

Let's check the TOP open positions and their current prices."""
import os, sys, django, requests
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity, Market
from decimal import Decimal
from collections import defaultdict

w = Wallet.objects.get(id=8)

# Calculate net position per market
net_shares = defaultdict(Decimal)
cost_basis = defaultdict(Decimal)

for t in Trade.objects.filter(wallet=w, side='BUY'):
    net_shares[t.market_id] += Decimal(str(t.size))
    cost_basis[t.market_id] += Decimal(str(t.size)) * Decimal(str(t.price))
for t in Trade.objects.filter(wallet=w, side='SELL'):
    net_shares[t.market_id] -= Decimal(str(t.size))
for a in Activity.objects.filter(wallet=w, activity_type__in=['MERGE', 'REDEEM']):
    net_shares[a.market_id] -= Decimal(str(a.size or 0))

# Top 20 open positions by shares
open_positions = [(mid, shares, cost_basis.get(mid, Decimal(0))) 
                  for mid, shares in net_shares.items() if shares > 10]
open_positions.sort(key=lambda x: -x[1])

print(f"Open positions with >10 shares: {len(open_positions)}")
print(f"\nTOP 30 by shares:")
total_shares = Decimal(0)
total_cost = Decimal(0)
for mid, shares, cost in open_positions[:30]:
    m = Market.objects.filter(id=mid).first()
    title = m.title[:60] if m else f"#{mid}"
    avg = cost / shares if shares > 0 else 0
    total_shares += shares
    total_cost += cost
    print(f"  {shares:10.1f} shares, cost=${cost:10.2f}, avg=${avg:.4f} | {title}")

print(f"\n  Subtotal top 30: {total_shares:.0f} shares, ${total_cost:.2f}")
print(f"  Total all open: {sum(s for _,s,_ in open_positions):.0f} shares")

# Check: how many are NEGATIVE positions (sold/redeemed more than bought)?
neg_positions = [(mid, shares) for mid, shares in net_shares.items() if shares < -1]
print(f"\n\nNegative positions (sold more than bought): {len(neg_positions)}")
total_neg = sum(s for _,s in neg_positions)
print(f"Total negative shares: {total_neg:.2f}")
# These come from conversion-created shares being redeemed
# without corresponding buys in that specific market

# Show top negative
neg_positions.sort(key=lambda x: x[1])
for mid, shares in neg_positions[:10]:
    m = Market.objects.filter(id=mid).first()
    title = m.title[:60] if m else f"#{mid}"
    print(f"  {shares:10.1f} shares | {title}")
