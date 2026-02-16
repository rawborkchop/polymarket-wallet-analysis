"""Analysis 5: Verify conversion mechanics and compute TRUE all-time PnL.
Conversion at $1/share creates 1 share in each child.
The conversion USDC should NOT be double-counted with the child buys."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity, Market
from decimal import Decimal
from collections import defaultdict
from django.db.models import Q

w = Wallet.objects.get(id=8)

# London Nov 12 example: 
# Parent conversion: 8396 shares * $1 = $8396 USDC
# This creates 8396 shares in EACH of 7 children
# So total "shares created" = 8396 * 7 = 58,773 shares
# But user only paid $8396, not $58,773

# In child "54F or below": user bought 8424 shares at ~$0.998
# But 8396 of those came FREE from the conversion
# Real buy was only 28 shares at $11 (the extra ones)

# Wait - the child shows 8424 shares bought. Let me check if the 
# conversion shares are SEPARATE from the trade shares.

# In neg-risk: CONVERSION on parent gives you 1 share of EVERY child
# Then user typically SELLS the "No" shares they don't want
# The child market BUYs are ADDITIONAL purchases beyond what conversion gave

# But looking at "54F or below": 8424 shares bought at $8407
# That's suspiciously close to 8396 (conversion size)
# Those BUYs might actually be the conversion creating shares!

# Let me check: are the child BUYs happening at the SAME TIME as conversions?
print("=== TIMING: Do child BUYs match parent CONVERSIONS? ===\n")

parent_m = Market.objects.filter(title='Highest temperature in London on November 12?').first()
nov12 = Market.objects.filter(Q(title__icontains='November 12') & Q(title__icontains='London'))

# Get conversion timestamps
convs = Activity.objects.filter(wallet=w, market_id=parent_m.id, activity_type='CONVERSION').order_by('timestamp')
conv_timestamps = {c.timestamp: Decimal(str(c.size or 0)) for c in convs}

# Check each child for buys at conversion timestamps
for m in nov12.exclude(id=parent_m.id):
    trades_at_conv = Trade.objects.filter(
        wallet=w, market_id=m.id, side='BUY',
        timestamp__in=conv_timestamps.keys()
    )
    if trades_at_conv.exists():
        print(f"  {m.title[:60]}")
        for t in trades_at_conv:
            conv_size = conv_timestamps.get(t.timestamp, 0)
            print(f"    BUY at conv_ts={t.timestamp}: size={t.size} price={t.price} (conv_size={conv_size})")

# The answer will tell us if child BUYs are duplicates of conversions

# NOW: compute what PM actually counts as PnL
# PM formula: position-level avg cost basis
# For neg-risk: the cost basis of a share obtained via conversion is $1/N where N = num outcomes
# (because user paid $1 and got N shares, each worth $1/N)
# OR: PM might track it differently - conversion cost = $1 per share for the specific outcome

# Actually in Polymarket neg-risk:
# SPLIT: user deposits $1 USDC → gets 1 "Yes" token for EACH outcome
# CONVERSION: user has a "Yes" token in outcome A → converts to "No" tokens in ALL OTHER outcomes
# MERGE: reverse of split - user has 1 token of each outcome → gets $1 back

# So CONVERSION is NOT a $1/share purchase. It's a token swap.
# User gives 1 "Yes" token of outcome A → gets 1 "No" token for outcomes B,C,D,E,F,G

# Let me recheck: what does usdc_size mean for conversions?
print(f"\n\n=== CONVERSION USDC meaning ===")
for c in convs:
    print(f"  ts={c.timestamp} size={c.size} usdc={c.usdc_size} outcome='{c.outcome}' asset='{c.asset}'")

# And check: are the conversions USDC_SIZE = SIZE (i.e., $1/share)?
print(f"\nConversion size == usdc_size? {all(Decimal(str(c.size)) == Decimal(str(c.usdc_size)) for c in convs)}")

# Total accounting across ALL markets for this wallet
print(f"\n\n{'='*80}")
print(f"GLOBAL ACCOUNTING")
print(f"{'='*80}")

all_conv = Activity.objects.filter(wallet=w, activity_type='CONVERSION')
all_split = Activity.objects.filter(wallet=w, activity_type='SPLIT')  
all_merge = Activity.objects.filter(wallet=w, activity_type='MERGE')
all_redeem = Activity.objects.filter(wallet=w, activity_type='REDEEM')
all_reward = Activity.objects.filter(wallet=w, activity_type='REWARD')
all_trades = Trade.objects.filter(wallet=w)

buy_cost = sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in all_trades.filter(side='BUY'))
sell_rev = sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in all_trades.filter(side='SELL'))
conv_usdc = sum(Decimal(str(a.usdc_size or 0)) for a in all_conv)
split_usdc = sum(Decimal(str(a.usdc_size or 0)) for a in all_split)
merge_usdc = sum(Decimal(str(a.usdc_size or 0)) for a in all_merge)
redeem_usdc = sum(Decimal(str(a.usdc_size or 0)) for a in all_redeem)
reward_usdc = sum(Decimal(str(a.usdc_size or 0)) for a in all_reward)

print(f"Buys:        ${buy_cost:.2f}")
print(f"Sells:       ${sell_rev:.2f}")
print(f"Conversions: ${conv_usdc:.2f}")
print(f"Splits:      ${split_usdc:.2f}")
print(f"Merges:      ${merge_usdc:.2f}")
print(f"Redeems:     ${redeem_usdc:.2f}")
print(f"Rewards:     ${reward_usdc:.2f}")

# Hypothesis: conversions are ALREADY included in the buy cost
# (the child market trade is the conversion expressed as a buy)
# So conversions should NOT be subtracted again
pnl_no_conv = sell_rev + redeem_usdc + merge_usdc + reward_usdc - buy_cost - split_usdc
print(f"\nPnL (no conv, no conversion): ${pnl_no_conv:.2f}")

# OR: conversions are an additional cost (user paid USDC for them)
pnl_with_conv = pnl_no_conv - conv_usdc
print(f"PnL (with conv as cost):      ${pnl_with_conv:.2f}")

# OR: conversions are revenue (user got USDC from them - unlikely)
pnl_conv_revenue = pnl_no_conv + conv_usdc
print(f"PnL (with conv as revenue):   ${pnl_conv_revenue:.2f}")

print(f"\nPolymarket official ALL: $25,000")
print(f"Gap from no-conv:  ${25000 - float(pnl_no_conv):.2f}")
print(f"Gap from with-conv: ${25000 - float(pnl_with_conv):.2f}")
print(f"Gap from conv-rev:  ${25000 - float(pnl_conv_revenue):.2f}")
