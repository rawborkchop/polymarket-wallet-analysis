"""Deep analysis 2: Understand neg-risk market structure.
Conversions and redeems are in DIFFERENT market_ids but same logical group.
Need to understand parent/child relationship."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity, Market
from decimal import Decimal
from collections import defaultdict
from datetime import datetime

w = Wallet.objects.get(id=8)

# Get all markets this user has interacted with
trade_markets = set(Trade.objects.filter(wallet=w).values_list('market_id', flat=True).distinct())
conv_markets = set(Activity.objects.filter(wallet=w, activity_type='CONVERSION').values_list('market_id', flat=True).distinct())
redeem_markets = set(Activity.objects.filter(wallet=w, activity_type='REDEEM').values_list('market_id', flat=True).distinct())

print(f"Trade markets: {len(trade_markets)}")
print(f"Conversion markets: {len(conv_markets)}")
print(f"Redeem markets: {len(redeem_markets)}")
print(f"Overlap trade & conversion: {len(trade_markets & conv_markets)}")
print(f"Overlap trade & redeem: {len(trade_markets & redeem_markets)}")
print(f"Overlap conversion & redeem: {len(conv_markets & redeem_markets)}")

# The key insight: user TRADES in market A, CONVERTS to get tokens in market B, 
# and REDEEMS in market B. But A and B have different market_ids.
# Let's group by title prefix to find siblings

# Get all market titles
all_market_ids = trade_markets | conv_markets | redeem_markets
markets = {m.id: m for m in Market.objects.filter(id__in=all_market_ids)}

# Group markets by "parent" topic (strip the specific outcome from title)
# E.g., "Will the highest temperature in London be between 65-66°F on September 2?"
# Parent: "Highest temperature in London on September 2"
import re

def extract_parent(title):
    if not title:
        return None
    # Try to match "Highest temperature in CITY on DATE?"
    m = re.match(r'.*(?:Highest temperature in \w+ on .+?\?)', title)
    if m:
        # Extract the date part
        m2 = re.search(r'(Highest temperature in \w+ on [^?]+)', title)
        if m2:
            return m2.group(1).strip()
    # Try "Elon Musk # tweets" pattern
    m3 = re.search(r'(Elon Musk.*?tweets.*?\?)', title)
    if m3:
        return m3.group(1).strip()
    return title

parent_groups = defaultdict(lambda: {'trade': set(), 'conv': set(), 'redeem': set()})

for mid in all_market_ids:
    m = markets.get(mid)
    title = m.title if m else ''
    parent = extract_parent(title) or f'unknown_{mid}'
    if mid in trade_markets:
        parent_groups[parent]['trade'].add(mid)
    if mid in conv_markets:
        parent_groups[parent]['conv'].add(mid)
    if mid in redeem_markets:
        parent_groups[parent]['redeem'].add(mid)

print(f"\n\nParent groups: {len(parent_groups)}")

# Find groups where user trades in one child and redeems in another
cross_groups = 0
for parent, data in sorted(parent_groups.items()):
    has_trades = bool(data['trade'])
    has_convs = bool(data['conv'])
    has_redeems = bool(data['redeem'])
    if has_convs and (has_trades or has_redeems):
        cross_groups += 1

print(f"Groups with conversions + (trades or redeems): {cross_groups}")

# Detailed look at top groups
print(f"\n\n=== TOP PARENT GROUPS (by conversion value) ===")
group_vals = []
for parent, data in parent_groups.items():
    conv_val = Decimal(0)
    for mid in data['conv']:
        convs = Activity.objects.filter(wallet=w, market_id=mid, activity_type='CONVERSION')
        conv_val += sum(Decimal(str(c.usdc_size or 0)) for c in convs)
    if conv_val > 0:
        group_vals.append((parent, data, conv_val))

group_vals.sort(key=lambda x: -x[2])

for parent, data, conv_val in group_vals[:5]:
    print(f"\n  PARENT: {parent}")
    print(f"    Trade markets: {len(data['trade'])}, Conv markets: {len(data['conv'])}, Redeem markets: {len(data['redeem'])}")
    print(f"    Conversion value: ${conv_val:.2f}")
    
    # Show trade detail
    for mid in data['trade']:
        m = markets.get(mid)
        trades = Trade.objects.filter(wallet=w, market_id=mid)
        buy_cost = sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in trades.filter(side='BUY'))
        sell_rev = sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in trades.filter(side='SELL'))
        print(f"    TRADE market '{m.title[:60] if m else mid}': buys=${buy_cost:.2f} sells=${sell_rev:.2f}")
    
    # Show conversion detail
    for mid in data['conv']:
        m = markets.get(mid)
        convs = Activity.objects.filter(wallet=w, market_id=mid, activity_type='CONVERSION')
        cv = sum(Decimal(str(c.usdc_size or 0)) for c in convs)
        print(f"    CONV  market '{m.title[:60] if m else mid}': {convs.count()} conversions, ${cv:.2f}")
    
    # Show redeem detail
    for mid in data['redeem']:
        m = markets.get(mid)
        reds = Activity.objects.filter(wallet=w, market_id=mid, activity_type='REDEEM')
        rv = sum(Decimal(str(r.usdc_size or 0)) for r in reds)
        print(f"    REDEEM market '{m.title[:60] if m else mid}': {reds.count()} redeems, ${rv:.2f}")

# Trace ONE complete lifecycle
print(f"\n\n{'='*80}")
print(f"FULL LIFECYCLE TRACE: {group_vals[0][0]}")
print(f"{'='*80}")

parent, data, _ = group_vals[0]
all_events = []
for mid in data['trade'] | data['conv'] | data['redeem']:
    m = markets.get(mid)
    title = m.title[:50] if m else f"#{mid}"
    for t in Trade.objects.filter(wallet=w, market_id=mid).order_by('timestamp'):
        all_events.append((t.timestamp, f"TRADE {t.side:4s} size={float(t.size):.2f} price={float(t.price):.4f} cost=${float(t.size)*float(t.price):.2f} [{title}]"))
    for a in Activity.objects.filter(wallet=w, market_id=mid).order_by('timestamp'):
        all_events.append((a.timestamp, f"{a.activity_type:12s} size={float(a.size or 0):.2f} usdc=${float(a.usdc_size or 0):.2f} [{title}]"))

all_events.sort()
for ts, desc in all_events:
    dt = datetime.fromtimestamp(ts)
    print(f"  {dt} {desc}")
