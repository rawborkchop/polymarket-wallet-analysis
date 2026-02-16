"""Analysis 8: The child market 63-64F has 12786 shares redeemed but only 4390 bought.
Where did the extra ~8396 shares come from? From the parent conversion!
This means: BUY in child A ($8407) → CONVERT on parent → creates shares in child B (63-64F)
The buy cost is in child A, but the redeem happens in child B.
Our calculator sees a $12786 redeem in B but only $1984 cost → huge fake profit.
Meanwhile child A has $8407 cost with no redeem → huge fake loss.
These cancel out at the GROUP level but not at individual market level."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity, Market
from decimal import Decimal
from django.db.models import Q

w = Wallet.objects.get(id=8)

# Complete picture for London Nov 12 GROUP
nov12 = Market.objects.filter(Q(title__icontains='November 12') & Q(title__icontains='London'))
market_ids = list(nov12.values_list('id', flat=True))

group_buy = Decimal(0)
group_sell = Decimal(0)
group_conv = Decimal(0)
group_merge = Decimal(0)
group_redeem = Decimal(0)
group_split = Decimal(0)

for m in nov12:
    mid = m.id
    buy = sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in Trade.objects.filter(wallet=w, market_id=mid, side='BUY'))
    sell = sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in Trade.objects.filter(wallet=w, market_id=mid, side='SELL'))
    conv = sum(Decimal(str(a.usdc_size or 0)) for a in Activity.objects.filter(wallet=w, market_id=mid, activity_type='CONVERSION'))
    merge = sum(Decimal(str(a.usdc_size or 0)) for a in Activity.objects.filter(wallet=w, market_id=mid, activity_type='MERGE'))
    redeem = sum(Decimal(str(a.usdc_size or 0)) for a in Activity.objects.filter(wallet=w, market_id=mid, activity_type='REDEEM'))
    split = sum(Decimal(str(a.usdc_size or 0)) for a in Activity.objects.filter(wallet=w, market_id=mid, activity_type='SPLIT'))
    
    group_buy += buy
    group_sell += sell
    group_conv += conv
    group_merge += merge
    group_redeem += redeem
    group_split += split

# The key insight for neg-risk groups:
# Total money IN = buys + splits + conversions_in
# Total money OUT = sells + merges + redeems + conversions_out
# But conversions are INTERNAL transfers, not real money flow

# Actually for this user:
# 1. Buys "No" shares in specific children at ~$1/share (REAL COST)
# 2. Conversion converts those into "Yes" shares in OTHER children (REDISTRIBUTION)
# 3. Sells unwanted children's shares (REAL REVENUE)
# 4. Redeems winner child at $1/share (REAL REVENUE)
# 5. Merge: combines children back into parent (REAL REVENUE at $1/share)

# So TRUE PnL = sell + redeem + merge - buy (conversions are neutral)
true_pnl = group_sell + group_redeem + group_merge - group_buy
print(f"London Nov 12 GROUP:")
print(f"  Buy:    ${group_buy:.2f}")
print(f"  Sell:   ${group_sell:.2f}")
print(f"  Conv:   ${group_conv:.2f} (neutral)")
print(f"  Merge:  ${group_merge:.2f}")
print(f"  Redeem: ${group_redeem:.2f}")
print(f"  TRUE PnL: ${true_pnl:.2f}")

# Now the BIG question: does this formula work GLOBALLY?
print(f"\n\n{'='*80}")
print(f"GLOBAL: sell + redeem + merge + reward - buy - split (ignore conversions)")
print(f"{'='*80}")

all_buy = sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in Trade.objects.filter(wallet=w, side='BUY'))
all_sell = sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in Trade.objects.filter(wallet=w, side='SELL'))
all_redeem = sum(Decimal(str(a.usdc_size or 0)) for a in Activity.objects.filter(wallet=w, activity_type='REDEEM'))
all_merge = sum(Decimal(str(a.usdc_size or 0)) for a in Activity.objects.filter(wallet=w, activity_type='MERGE'))
all_reward = sum(Decimal(str(a.usdc_size or 0)) for a in Activity.objects.filter(wallet=w, activity_type='REWARD'))
all_split = sum(Decimal(str(a.usdc_size or 0)) for a in Activity.objects.filter(wallet=w, activity_type='SPLIT'))
all_conv = sum(Decimal(str(a.usdc_size or 0)) for a in Activity.objects.filter(wallet=w, activity_type='CONVERSION'))

global_pnl = all_sell + all_redeem + all_merge + all_reward - all_buy - all_split
print(f"  Buy:     ${all_buy:.2f}")
print(f"  Sell:    ${all_sell:.2f}")
print(f"  Redeem:  ${all_redeem:.2f}")
print(f"  Merge:   ${all_merge:.2f}")
print(f"  Reward:  ${all_reward:.2f}")
print(f"  Split:   ${all_split:.2f}")
print(f"  Conv:    ${all_conv:.2f} (excluded)")
print(f"  PnL:     ${global_pnl:.2f}")
print(f"  PM:      $25,000")
print(f"  Gap:     ${25000 - float(global_pnl):.2f}")

# This is the SAME as our original cash flow which was -$150k
# So the fundamental problem isn't conversions being mis-categorized
# It's that this user is LOSING money overall

# Wait - maybe PM uses mark-to-market for open positions?
# Let's check: how much is still in open positions?
print(f"\n\n=== OPEN POSITIONS VALUE ===")
# Net shares per market (buy - sell - merge - redeem)
from collections import defaultdict
net_by_market = defaultdict(Decimal)
cost_by_market = defaultdict(Decimal)

for t in Trade.objects.filter(wallet=w, side='BUY'):
    net_by_market[t.market_id] += Decimal(str(t.size))
    cost_by_market[t.market_id] += Decimal(str(t.size)) * Decimal(str(t.price))
for t in Trade.objects.filter(wallet=w, side='SELL'):
    net_by_market[t.market_id] -= Decimal(str(t.size))
for a in Activity.objects.filter(wallet=w, activity_type='MERGE'):
    net_by_market[a.market_id] -= Decimal(str(a.size or 0))
for a in Activity.objects.filter(wallet=w, activity_type='REDEEM'):
    net_by_market[a.market_id] -= Decimal(str(a.size or 0))

total_open_shares = Decimal(0)
total_open_cost = Decimal(0)
open_count = 0
for mid, shares in net_by_market.items():
    if shares > 1:
        open_count += 1
        total_open_shares += shares
        total_open_cost += cost_by_market.get(mid, Decimal(0))

print(f"  Markets with open positions: {open_count}")
print(f"  Total open shares: {total_open_shares:.2f}")
print(f"  Total cost in open positions: ${total_open_cost:.2f}")
print(f"  If valued at avg ~$0.95/share: ${total_open_shares * Decimal('0.95'):.2f}")
print(f"  PnL + open value at $0.95: ${float(global_pnl) + float(total_open_shares) * 0.95:.2f}")
print(f"  PnL + open value at $1.00: ${float(global_pnl) + float(total_open_shares):.2f}")
