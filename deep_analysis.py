"""Deep analysis: understand conversion mechanics from actual DB data.
Pick a specific market with conversions+redeems and trace the full lifecycle."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity, Market
from decimal import Decimal
from collections import defaultdict

w = Wallet.objects.get(id=8)

# Find a market with conversions AND redeems (resolved, so we can verify)
conv_markets = Activity.objects.filter(wallet=w, activity_type='CONVERSION').values_list('market_id', flat=True).distinct()
redeem_markets = Activity.objects.filter(wallet=w, activity_type='REDEEM').values_list('market_id', flat=True).distinct()
both = set(conv_markets) & set(redeem_markets)
print(f"Markets with both conversions AND redeems: {len(both)}")

# Pick one with decent value
best = None
best_val = 0
for mid in both:
    redeems = Activity.objects.filter(wallet=w, market_id=mid, activity_type='REDEEM')
    val = sum(Decimal(str(r.usdc_size or 0)) for r in redeems)
    if val > best_val:
        best_val = val
        best = mid

print(f"\nBest example market: {best} (redeem value ${best_val:.2f})")

# Dump ALL events for this market chronologically
print(f"\n{'='*80}")
print(f"FULL EVENT LOG FOR MARKET {best}")
print(f"{'='*80}")

market = Market.objects.filter(id=best).first()
if market:
    print(f"Title: {market.title}")

trades = list(Trade.objects.filter(wallet=w, market_id=best).order_by('timestamp'))
activities = list(Activity.objects.filter(wallet=w, market_id=best).order_by('timestamp'))

events = []
for t in trades:
    events.append(('TRADE', t.timestamp, t.side, Decimal(str(t.size)), Decimal(str(t.price)), t.outcome or '', Decimal(str(t.size))*Decimal(str(t.price)), t.asset or ''))
for a in activities:
    events.append((a.activity_type, a.timestamp, '', Decimal(str(a.size or 0)), Decimal(0), a.outcome or '', Decimal(str(a.usdc_size or 0)), a.asset or ''))

events.sort(key=lambda e: e[1])

from datetime import datetime
for ev in events:
    etype, ts, side, size, price, outcome, usdc, asset = ev
    dt = datetime.fromtimestamp(ts)
    if etype == 'TRADE':
        print(f"  {dt} TRADE {side:4s} size={size:.2f} price={price:.4f} cost=${usdc:.2f} outcome={outcome[:30]} asset={asset[:20]}")
    else:
        print(f"  {dt} {etype:12s} size={size:.2f} usdc=${usdc:.2f} outcome={outcome[:30]} asset={asset[:20]}")

# Now check: what's the PARENT market (condition group)?
# Neg-risk markets share a parent. Conversions move tokens between siblings.
print(f"\n\n{'='*80}")
print(f"SIBLING MARKETS ANALYSIS")
print(f"{'='*80}")

# Find markets with similar titles (same temperature group)
if market:
    # Extract base pattern from title
    title = market.title
    print(f"Target: {title}")
    
    # Find the "parent" group - look at all conversion markets and group by title prefix
    # Temperature markets follow pattern: "Highest temperature in London on DATE?"
    # or "Will the highest temperature in London be between X-Y°F on DATE?"
    
# Let's also check a few more conversion-only markets to understand the pattern
print(f"\n\n{'='*80}")
print(f"SAMPLE CONVERSION-ONLY MARKETS (no trades, no redeems)")  
print(f"{'='*80}")

conv_only_no_redeem = []
for mid in conv_markets:
    tc = Trade.objects.filter(wallet=w, market_id=mid).count()
    rc = Activity.objects.filter(wallet=w, market_id=mid, activity_type='REDEEM').count()
    if tc == 0 and rc == 0:
        convs = Activity.objects.filter(wallet=w, market_id=mid, activity_type='CONVERSION')
        val = sum(Decimal(str(c.usdc_size or 0)) for c in convs)
        conv_only_no_redeem.append((mid, convs.count(), val))

conv_only_no_redeem.sort(key=lambda x: -x[2])
print(f"Markets with conversions but NO trades and NO redeems: {len(conv_only_no_redeem)}")
for mid, cnt, val in conv_only_no_redeem[:10]:
    m = Market.objects.filter(id=mid).first()
    title = m.title if m else f"#{mid}"
    print(f"  {title[:70]}: {cnt} conversions, ${val:.2f}")

# Key question: do conversions appear in PAIRS across sibling markets?
print(f"\n\n{'='*80}")
print(f"CONVERSION PAIRING ANALYSIS")
print(f"{'='*80}")

# Group all conversions by timestamp to see if they come in pairs
all_convs = Activity.objects.filter(wallet=w, activity_type='CONVERSION').order_by('timestamp')
by_ts = defaultdict(list)
for c in all_convs:
    by_ts[c.timestamp].append(c)

paired = 0
unpaired = 0
for ts, convs in by_ts.items():
    if len(convs) == 2:
        paired += 1
    elif len(convs) == 1:
        unpaired += 1

print(f"Conversions at same timestamp (paired): {paired} timestamps ({paired*2} conversions)")
print(f"Conversions alone: {unpaired}")
print(f"Other (3+): {len(by_ts) - paired - unpaired}")

# Show a few pairs
for ts, convs in sorted(by_ts.items())[:5]:
    dt = datetime.fromtimestamp(ts)
    print(f"\n  {dt}:")
    for c in convs:
        m = Market.objects.filter(id=c.market_id).first()
        title = m.title[:50] if m else f"#{c.market_id}"
        print(f"    {c.activity_type} market={title} size={c.size} usdc=${c.usdc_size} outcome={c.outcome}")
