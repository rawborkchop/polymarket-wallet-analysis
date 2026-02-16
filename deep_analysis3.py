"""Deep analysis 3: Find the ACTUAL sibling markets.
The conversion market is the PARENT (e.g., "Highest temperature in London on Nov 12?")
The trade/redeem markets are CHILDREN (e.g., "Will the highest temp be between 46-47F on Nov 12?")
"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity, Market
from decimal import Decimal
from datetime import datetime

w = Wallet.objects.get(id=8)

# Take "Highest temperature in London on November 12?" as example
# Find all markets with "November 12" and "London" in title
from django.db.models import Q
nov12_markets = Market.objects.filter(Q(title__icontains='November 12') & Q(title__icontains='London'))
print(f"Markets matching 'London November 12': {nov12_markets.count()}")

for m in nov12_markets[:20]:
    tc = Trade.objects.filter(wallet=w, market_id=m.id).count()
    cc = Activity.objects.filter(wallet=w, market_id=m.id, activity_type='CONVERSION').count()
    rc = Activity.objects.filter(wallet=w, market_id=m.id, activity_type='REDEEM').count()
    if tc or cc or rc:
        print(f"  Market {m.id}: '{m.title[:70]}' trades={tc} conv={cc} redeem={rc}")

# Now trace the FULL picture for this date
print(f"\n\n{'='*80}")
print(f"COMPLETE LIFECYCLE: London November 12")
print(f"{'='*80}")

all_events = []
for m in nov12_markets:
    title = m.title[:50]
    mid = m.id
    for t in Trade.objects.filter(wallet=w, market_id=mid).order_by('timestamp'):
        cost = float(t.size) * float(t.price)
        all_events.append((t.timestamp, f"TRADE {t.side:4s} size={float(t.size):8.2f} price={float(t.price):.4f} cost=${cost:8.2f} [{title}]"))
    for a in Activity.objects.filter(wallet=w, market_id=mid).order_by('timestamp'):
        all_events.append((a.timestamp, f"{a.activity_type:12s} size={float(a.size or 0):8.2f} usdc=${float(a.usdc_size or 0):8.2f} [{title}]"))

all_events.sort()
total_buy = 0
total_sell = 0
total_conv = 0
total_redeem = 0
for ts, desc in all_events:
    dt = datetime.fromtimestamp(ts)
    print(f"  {dt} {desc}")
    if 'TRADE BUY' in desc:
        total_buy += float(desc.split('cost=$')[1].split()[0])
    elif 'TRADE SELL' in desc:
        total_sell += float(desc.split('cost=$')[1].split()[0])
    elif 'CONVERSION' in desc:
        total_conv += float(desc.split('usdc=$')[1].split()[0])
    elif 'REDEEM' in desc:
        total_redeem += float(desc.split('usdc=$')[1].split()[0])

print(f"\n  Summary:")
print(f"    Total buys: ${total_buy:.2f}")
print(f"    Total sells: ${total_sell:.2f}")
print(f"    Total conversions: ${total_conv:.2f}")
print(f"    Total redeems: ${total_redeem:.2f}")
print(f"    Cash flow (sell+redeem-buy): ${total_sell + total_redeem - total_buy:.2f}")
print(f"    Cash flow (sell+redeem-buy-conv): ${total_sell + total_redeem - total_buy - total_conv:.2f}")

# KEY QUESTION: Does the conversion value equal the buy cost of the position?
# In neg-risk: user pays $X via conversion to get shares of specific outcome
# Then redeems for $1/share if winner
# PnL should be: redeem - conversion cost (NOT redeem - buy cost)
