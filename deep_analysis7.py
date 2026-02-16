"""Analysis 7: Quantify the exact impact on avg cost calculator.
The calculator skips redeems when there's no position to match.
How much PnL is lost from unmatched redeems?

Also: in markets WITH trades, the conversion creates EXTRA positions
that the calculator doesn't know about. When those redeem, the
calculator matches against the trade-based position (wrong avg_cost)."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity
from decimal import Decimal
from collections import defaultdict

w = Wallet.objects.get(id=8)

# 1) Redeems in markets with NO trades at all (completely lost)
redeem_markets = Activity.objects.filter(wallet=w, activity_type='REDEEM').values_list('market_id', flat=True).distinct()
lost_redeems_no_trades = Decimal(0)
lost_count_no_trades = 0
for mid in redeem_markets:
    if not Trade.objects.filter(wallet=w, market_id=mid).exists():
        redeems = Activity.objects.filter(wallet=w, market_id=mid, activity_type='REDEEM')
        val = sum(Decimal(str(r.usdc_size or 0)) for r in redeems)
        if val > 0:
            lost_redeems_no_trades += val
            lost_count_no_trades += redeems.count()

print(f"1) Redeems in markets with NO trades: {lost_count_no_trades} redeems, ${lost_redeems_no_trades:.2f}")

# 2) In markets WITH trades: check if conversion creates more shares than trades
# This means redeems exceed what the calculator can match
conv_markets = set(
    Activity.objects.filter(wallet=w, activity_type='CONVERSION')
    .values_list('market_id', flat=True).distinct()
)

# For each conversion market, find its children (markets in the same group)
# Actually, the conversion is on the PARENT. Children have trades.
# The problem: conversion on parent → creates shares in children → 
# children have MORE shares than their BUYs account for

# Let me check: for markets with BOTH trades and redeems,
# do the redeem shares ever exceed buy shares?
print(f"\n2) Markets where redeem shares > buy shares:")
over_redeemed = Decimal(0)
over_count = 0
for mid in redeem_markets:
    buy_shares = sum(Decimal(str(t.size)) for t in Trade.objects.filter(wallet=w, market_id=mid, side='BUY'))
    sell_shares = sum(Decimal(str(t.size)) for t in Trade.objects.filter(wallet=w, market_id=mid, side='SELL'))
    merge_shares = sum(Decimal(str(a.size or 0)) for a in Activity.objects.filter(wallet=w, market_id=mid, activity_type='MERGE'))
    redeem_shares = sum(Decimal(str(r.size or 0)) for r in Activity.objects.filter(wallet=w, market_id=mid, activity_type='REDEEM'))
    redeem_usdc = sum(Decimal(str(r.usdc_size or 0)) for r in Activity.objects.filter(wallet=w, market_id=mid, activity_type='REDEEM'))
    
    net_position = buy_shares - sell_shares - merge_shares
    if redeem_shares > net_position and redeem_usdc > 0:
        excess = redeem_shares - max(net_position, Decimal(0))
        # The excess redeems are from conversion-created shares
        # At $1/share redeem, excess PnL impact = excess * (1 - avg_cost_from_conversion)
        # But since conversion gives shares at $1, cost basis should be ~$1
        # So PnL from conversion redeems ≈ 0 (redeem $1 - cost $1 = $0)
        over_count += 1
        over_redeemed += redeem_usdc

print(f"  Markets with excess redeems: {over_count}")
print(f"  Total redeem value in those markets: ${over_redeemed:.2f}")

# 3) The REAL question: what PnL does Polymarket attribute to conversion-based positions?
# If cost basis from conversion = $1/share, and redeem = $1/share → PnL = $0
# If cost basis from conversion = $0 (free) → PnL = $1/share (all profit)
# In reality: user paid ~$1 to buy "No" in a child, then converted
# The conversion redistributes those shares → cost basis in new children ≈ proportional

# For our calculator: the key fix would be to:
# - When processing CONVERSION on parent, create positions in children
# - Cost basis per child = conversion USDC / num_children
# - Then redeems in those children can match against these positions

# But we don't KNOW which children got shares from the conversion
# because the conversion data has empty outcome/asset

# SIMPLER APPROACH: treat conversion markets as having net-zero PnL
# (cost ~$1, redeem ~$1 for winner, other children expire worthless)
# Focus only on the direct-trade markets

# Let's compute PnL excluding ALL conversion-related markets
print(f"\n\n3) PnL if we exclude ALL markets touched by conversions:")
# Find all market_ids that have conversions (parent markets)
parent_conv_mids = set(Activity.objects.filter(wallet=w, activity_type='CONVERSION').values_list('market_id', flat=True))
print(f"  Parent conversion markets: {len(parent_conv_mids)}")

# These parents are "Highest temperature in London on DATE?" 
# We need to also find their children
# Children have similar titles but are different markets
# For now, just exclude markets where redeems have no matching buys

# Actually, let's just compute a simple cash-flow PnL for ONLY markets with trades
trade_mids = set(Trade.objects.filter(wallet=w).values_list('market_id', flat=True))
print(f"  Markets with trades: {len(trade_mids)}")

buy_total = Decimal(0)
sell_total = Decimal(0)
redeem_total = Decimal(0)
merge_total = Decimal(0)

for mid in trade_mids:
    buy_total += sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in Trade.objects.filter(wallet=w, market_id=mid, side='BUY'))
    sell_total += sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in Trade.objects.filter(wallet=w, market_id=mid, side='SELL'))
    redeem_total += sum(Decimal(str(r.usdc_size or 0)) for r in Activity.objects.filter(wallet=w, market_id=mid, activity_type='REDEEM'))
    merge_total += sum(Decimal(str(m.usdc_size or 0)) for m in Activity.objects.filter(wallet=w, market_id=mid, activity_type='MERGE'))

print(f"\n  Trade-only markets:")
print(f"    Buys:    ${buy_total:.2f}")
print(f"    Sells:   ${sell_total:.2f}")
print(f"    Redeems: ${redeem_total:.2f}")
print(f"    Merges:  ${merge_total:.2f}")
print(f"    Cash PnL: ${sell_total + redeem_total + merge_total - buy_total:.2f}")
print(f"    + lost redeems from no-trade markets: ${lost_redeems_no_trades:.2f}")
print(f"    Adjusted PnL: ${sell_total + redeem_total + merge_total - buy_total + lost_redeems_no_trades:.2f}")
