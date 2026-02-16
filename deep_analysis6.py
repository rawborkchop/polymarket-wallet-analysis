"""Analysis 6: Understand what conversion ACTUALLY does in the data.
Key question: When a CONVERSION happens on parent market,
do the child markets get new TRADE BUYs automatically?
Or are the BUYs in children INDEPENDENT trades?"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity, Market
from decimal import Decimal
from datetime import datetime
from django.db.models import Q

w = Wallet.objects.get(id=8)

# Focus on child "54F or below" (market 11801) which has:
# - 8424 shares bought at $8407 (suspicious: ~8396 from conversion)
# - Only 28 shares redeemed
m_54 = Market.objects.get(id=11801)
print(f"Market: {m_54.title}")

# Get ALL buys in this child, sorted by time
buys = Trade.objects.filter(wallet=w, market_id=11801, side='BUY').order_by('timestamp')
print(f"\nBuys ({buys.count()} total):")
for t in buys:
    dt = datetime.fromtimestamp(t.timestamp)
    print(f"  {dt} size={float(t.size):10.2f} price={float(t.price):.6f} cost=${float(t.size)*float(t.price):8.2f}")

# Get conversions on parent
parent_m = Market.objects.filter(title='Highest temperature in London on November 12?').first()
convs = Activity.objects.filter(wallet=w, market_id=parent_m.id, activity_type='CONVERSION').order_by('timestamp')
print(f"\nParent conversions:")
for c in convs:
    dt = datetime.fromtimestamp(c.timestamp)
    print(f"  {dt} size={float(c.size):10.2f} usdc=${float(c.usdc_size):8.2f}")

# CRITICAL OBSERVATION: The buys in child "54F or below" are:
# - 1545 shares at $0.998 right before first conversion
# - 3897 shares at $0.998 right before second conversion
# etc.
# These look like the SPLIT part of the neg-risk operation:
# 1. User buys "No" tokens in child market at ~$1 each
# 2. System converts those into positions across outcomes
# So the BUYs ARE the real cost, and conversions are just the REDISTRIBUTION

# If that's the case, then conversions should be NEUTRAL for PnL
# The cost is already in the child BUYs
# And this would explain why our original cash flow was so negative:
# We're counting the child BUYs (the real cost) but the conversions
# redistribute the positions - without conversions in our model,
# the positions in non-traded children are invisible

# Verify: total buy cost in children near conversion timestamps
print(f"\n\n=== BUYs NEAR CONVERSION TIMESTAMPS ===")
for c in convs:
    # Find buys in ANY child within 60 seconds of this conversion
    nearby_buys = Trade.objects.filter(
        wallet=w, market_id__in=[11798,11799,11800,11801,11802,11803,11804],
        side='BUY',
        timestamp__gte=c.timestamp - 120,
        timestamp__lte=c.timestamp + 10,
    ).order_by('timestamp')
    
    dt = datetime.fromtimestamp(c.timestamp)
    conv_size = float(c.size)
    print(f"\n  CONV at {dt}: size={conv_size:.2f}")
    total_nearby = 0
    for t in nearby_buys:
        tdt = datetime.fromtimestamp(t.timestamp)
        m = Market.objects.get(id=t.market_id)
        cost = float(t.size) * float(t.price)
        total_nearby += cost
        diff = t.timestamp - c.timestamp
        print(f"    [{diff:+4d}s] BUY {m.title[50:70]:20s} size={float(t.size):8.2f} price={float(t.price):.4f} cost=${cost:.2f}")
    print(f"    Total nearby buy cost: ${total_nearby:.2f} (conv_usdc=${float(c.usdc_size):.2f})")
