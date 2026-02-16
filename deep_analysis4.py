"""Deep analysis 4: Precise accounting for London Nov 12 temperature market.
Understand the ACTUAL PnL flow vs what our calculator computes."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity, Market
from decimal import Decimal
from collections import defaultdict
from django.db.models import Q

w = Wallet.objects.get(id=8)

# All "London November 12" markets
nov12 = Market.objects.filter(Q(title__icontains='November 12') & Q(title__icontains='London'))
market_ids = list(nov12.values_list('id', flat=True))

# Group trades by child market
print("=== PER-CHILD-MARKET BREAKDOWN ===\n")
for m in nov12:
    trades = Trade.objects.filter(wallet=w, market_id=m.id).order_by('timestamp')
    convs = Activity.objects.filter(wallet=w, market_id=m.id, activity_type='CONVERSION')
    redeems = Activity.objects.filter(wallet=w, market_id=m.id, activity_type='REDEEM')
    merges = Activity.objects.filter(wallet=w, market_id=m.id, activity_type='MERGE')
    
    if not trades.exists() and not convs.exists() and not redeems.exists():
        continue
    
    buy_cost = sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in trades.filter(side='BUY'))
    buy_shares = sum(Decimal(str(t.size)) for t in trades.filter(side='BUY'))
    sell_rev = sum(Decimal(str(t.size))*Decimal(str(t.price)) for t in trades.filter(side='SELL'))
    sell_shares = sum(Decimal(str(t.size)) for t in trades.filter(side='SELL'))
    conv_val = sum(Decimal(str(c.usdc_size or 0)) for c in convs)
    conv_shares = sum(Decimal(str(c.size or 0)) for c in convs)
    redeem_val = sum(Decimal(str(r.usdc_size or 0)) for r in redeems)
    redeem_shares = sum(Decimal(str(r.size or 0)) for r in redeems)
    merge_val = sum(Decimal(str(mg.usdc_size or 0)) for mg in merges)
    merge_shares = sum(Decimal(str(mg.size or 0)) for mg in merges)
    
    print(f"  {m.title[:70]}")
    print(f"    BUY:    {buy_shares:10.2f} shares, ${buy_cost:10.2f}")
    print(f"    SELL:   {sell_shares:10.2f} shares, ${sell_rev:10.2f}")
    print(f"    CONV:   {conv_shares:10.2f} shares, ${conv_val:10.2f}")
    print(f"    MERGE:  {merge_shares:10.2f} shares, ${merge_val:10.2f}")
    print(f"    REDEEM: {redeem_shares:10.2f} shares, ${redeem_val:10.2f}")
    net_shares = buy_shares - sell_shares - merge_shares - redeem_shares
    print(f"    Net shares remaining: {net_shares:.2f}")
    print()

# KEY INSIGHT: In neg-risk, a CONVERSION on the PARENT market means:
# User deposited $X USDC → received 1 share of EACH outcome (child market)
# Then user SELLS the outcomes they don't want, KEEPS the one they bet on
# The conversion IS the buy — it creates positions in ALL children simultaneously

# So the TRUE cost of a position in a child is:
# conversion_cost_per_share - sell_revenue_of_other_children_per_share

# What about the $8396 in conversions on the parent "Highest temperature in London on November 12?"
# This created 8396 shares in EACH child market
# The user then sold the children they didn't want (those SELL trades early on)

# Let's verify: conversion shares should roughly equal the "No" position sizes
print("\n=== CONVERSION FLOW VERIFICATION ===")
parent_market = Market.objects.filter(title='Highest temperature in London on November 12?').first()
if parent_market:
    convs = Activity.objects.filter(wallet=w, market_id=parent_market.id, activity_type='CONVERSION').order_by('timestamp')
    total_conv_shares = sum(Decimal(str(c.size or 0)) for c in convs)
    total_conv_usdc = sum(Decimal(str(c.usdc_size or 0)) for c in convs)
    print(f"Parent market conversions: {convs.count()}")
    print(f"Total shares created: {total_conv_shares:.2f}")
    print(f"Total USDC spent: ${total_conv_usdc:.2f}")
    print(f"Effective price per share: ${total_conv_usdc/total_conv_shares:.4f}")
    
    # Each conversion creates 1 share in EACH child
    # So $8396 bought 8396 shares of EVERY outcome
    # Real cost per outcome depends on how many outcomes there are
    child_count = nov12.exclude(id=parent_market.id).count()
    print(f"Number of child markets: {child_count}")
    print(f"Effective cost per outcome: ${total_conv_usdc/Decimal(child_count):.2f} (if evenly split)")
    
    # The correct PnL for this group:
    # COST = total conversions ($8396) + direct buys in children
    # REVENUE = sells in children + redeems in children + merges
    all_buys = sum(
        Decimal(str(t.size))*Decimal(str(t.price))
        for t in Trade.objects.filter(wallet=w, market_id__in=market_ids, side='BUY')
    )
    all_sells = sum(
        Decimal(str(t.size))*Decimal(str(t.price))
        for t in Trade.objects.filter(wallet=w, market_id__in=market_ids, side='SELL')
    )
    all_redeems = sum(
        Decimal(str(r.usdc_size or 0))
        for r in Activity.objects.filter(wallet=w, market_id__in=market_ids, activity_type='REDEEM')
    )
    all_merges = sum(
        Decimal(str(mg.usdc_size or 0))
        for mg in Activity.objects.filter(wallet=w, market_id__in=market_ids, activity_type='MERGE')
    )
    
    print(f"\n  GROUP TOTALS:")
    print(f"    Conversion cost: ${total_conv_usdc:.2f}")
    print(f"    Direct buys:     ${all_buys:.2f}")
    print(f"    Total cost:      ${total_conv_usdc + all_buys:.2f}")
    print(f"    Sells:           ${all_sells:.2f}")
    print(f"    Redeems:         ${all_redeems:.2f}")
    print(f"    Merges:          ${all_merges:.2f}")
    print(f"    Total revenue:   ${all_sells + all_redeems + all_merges:.2f}")
    print(f"    TRUE PnL:        ${all_sells + all_redeems + all_merges - total_conv_usdc - all_buys:.2f}")
    print(f"    Our calc PnL (ignoring conv): ${all_sells + all_redeems + all_merges - all_buys:.2f}")
