"""Analysis 3: Neg-risk market impact.
In neg-risk markets, user buys BOTH sides (No tokens for multiple outcomes).
Conversions convert between conditional tokens. If we don't handle this,
cost basis gets inflated massively.

Key question: How much of the $613k in buys is double-counted from neg-risk?"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity, Market
from decimal import Decimal
from collections import defaultdict

w = Wallet.objects.get(id=8)

# Find markets where user has conversions (indicator of neg-risk)
conv_markets = set(
    Activity.objects.filter(wallet=w, activity_type='CONVERSION')
    .values_list('market_id', flat=True).distinct()
)
print(f"Markets with conversions (neg-risk indicators): {len(conv_markets)}")

# Calculate buy cost in neg-risk vs normal markets
negrisk_buys = Decimal(0)
normal_buys = Decimal(0)
negrisk_sells = Decimal(0) 
normal_sells = Decimal(0)
negrisk_trade_count = 0
normal_trade_count = 0

all_trades = Trade.objects.filter(wallet=w)
for t in all_trades:
    cost = Decimal(str(t.size)) * Decimal(str(t.price))
    if t.market_id in conv_markets:
        if t.side == 'BUY':
            negrisk_buys += cost
        else:
            negrisk_sells += cost
        negrisk_trade_count += 1
    else:
        if t.side == 'BUY':
            normal_buys += cost
        else:
            normal_sells += cost
        normal_trade_count += 1

print(f"\nNeg-risk markets:")
print(f"  Trades: {negrisk_trade_count}")
print(f"  Buys: ${negrisk_buys:.2f}")
print(f"  Sells: ${negrisk_sells:.2f}")
print(f"  Net: ${negrisk_sells - negrisk_buys:.2f}")

print(f"\nNormal markets:")
print(f"  Trades: {normal_trade_count}")
print(f"  Buys: ${normal_buys:.2f}")
print(f"  Sells: ${normal_sells:.2f}")
print(f"  Net: ${normal_sells - normal_buys:.2f}")

# For neg-risk markets, check outcomes
print(f"\n\n=== Neg-risk market outcome analysis ===")
for mid in list(conv_markets)[:5]:
    trades = Trade.objects.filter(wallet=w, market_id=mid)
    outcomes = defaultdict(lambda: {'buys': Decimal(0), 'sells': Decimal(0), 'count': 0})
    for t in trades:
        cost = Decimal(str(t.size)) * Decimal(str(t.price))
        key = t.outcome or '(empty)'
        outcomes[key]['count'] += 1
        if t.side == 'BUY':
            outcomes[key]['buys'] += cost
        else:
            outcomes[key]['sells'] += cost
    
    convs = Activity.objects.filter(wallet=w, market_id=mid, activity_type='CONVERSION')
    redeems = Activity.objects.filter(wallet=w, market_id=mid, activity_type='REDEEM')
    redeem_val = sum(Decimal(str(r.usdc_size or 0)) for r in redeems)
    
    market = Market.objects.filter(id=mid).first()
    title = market.title[:60] if market else f"Market#{mid}"
    print(f"\n  {title}")
    print(f"  Conversions: {convs.count()}, Redeems: {redeems.count()} (${redeem_val:.2f})")
    for outcome, data in outcomes.items():
        net = data['sells'] - data['buys']
        print(f"    {outcome[:30]}: {data['count']} trades, buys=${data['buys']:.2f} sells=${data['sells']:.2f} net=${net:.2f}")

# What % of total buys are neg-risk?
total_buys = negrisk_buys + normal_buys
print(f"\n\n=== Summary ===")
print(f"Total buys: ${total_buys:.2f}")
print(f"Neg-risk buys: ${negrisk_buys:.2f} ({negrisk_buys/total_buys*100:.1f}%)")
print(f"Normal buys: ${normal_buys:.2f} ({normal_buys/total_buys*100:.1f}%)")
print(f"\nIf neg-risk conversions offset buys, effective buys would be ${normal_buys:.2f}")
print(f"Cash flow with adjusted buys: ${normal_sells + negrisk_sells + Decimal('390911.48') + Decimal('23369.33') + Decimal('26.20') - normal_buys - Decimal('399.98'):.2f}")
