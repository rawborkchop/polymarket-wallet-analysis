"""Analysis 1: Impact of CONVERSIONS on PnL.
This wallet has 654 conversions worth $137k. Are we handling them correctly?
Conversions in neg-risk markets split/merge positions — ignoring them may corrupt cost basis."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity
from decimal import Decimal
from collections import defaultdict

w = Wallet.objects.get(id=8)
convs = Activity.objects.filter(wallet=w, activity_type='CONVERSION').order_by('timestamp')
print(f"Total conversions: {convs.count()}")
print(f"Total USDC value: ${sum(Decimal(str(a.usdc_size or 0)) for a in convs):.2f}")

# Group by market
by_market = defaultdict(list)
for c in convs:
    by_market[c.market_id].append(c)

print(f"Markets with conversions: {len(by_market)}")

# For each market with conversions, check if there are also trades/redeems
for mid, conv_list in sorted(by_market.items(), key=lambda x: -len(x[1]))[:10]:
    trades = Trade.objects.filter(wallet=w, market_id=mid)
    redeems = Activity.objects.filter(wallet=w, market_id=mid, activity_type='REDEEM')
    splits = Activity.objects.filter(wallet=w, market_id=mid, activity_type='SPLIT')
    merges = Activity.objects.filter(wallet=w, market_id=mid, activity_type='MERGE')
    
    conv_usdc = sum(Decimal(str(c.usdc_size or 0)) for c in conv_list)
    buy_cost = sum(Decimal(str(t.size)) * Decimal(str(t.price)) for t in trades.filter(side='BUY'))
    sell_rev = sum(Decimal(str(t.size)) * Decimal(str(t.price)) for t in trades.filter(side='SELL'))
    redeem_usdc = sum(Decimal(str(r.usdc_size or 0)) for r in redeems)
    
    market_title = conv_list[0].title or f"Market#{mid}"
    print(f"\n  Market {mid}: {market_title[:60]}")
    print(f"    Conversions: {len(conv_list)} (${conv_usdc:.2f})")
    print(f"    Trades: {trades.count()} (buys=${buy_cost:.2f}, sells=${sell_rev:.2f})")
    print(f"    Redeems: {redeems.count()} (${redeem_usdc:.2f})")
    print(f"    Splits: {splits.count()}, Merges: {merges.count()}")
    print(f"    Cash flow: ${sell_rev + redeem_usdc - buy_cost:.2f}")

# Check: what outcomes do conversions have?
print("\n\n=== Conversion outcomes ===")
outcome_counts = defaultdict(int)
for c in convs:
    outcome_counts[c.outcome or '(empty)'] += 1
for outcome, count in sorted(outcome_counts.items(), key=lambda x: -x[1])[:10]:
    print(f"  {outcome}: {count}")

# Key question: do conversions create positions we're not tracking?
print("\n\n=== Markets with conversions but NO trades ===")
conv_only = 0
for mid, conv_list in by_market.items():
    trade_count = Trade.objects.filter(wallet=w, market_id=mid).count()
    if trade_count == 0:
        conv_only += 1
        conv_usdc = sum(Decimal(str(c.usdc_size or 0)) for c in conv_list)
        title = conv_list[0].title or f"Market#{mid}"
        print(f"  {title[:60]}: {len(conv_list)} conversions, ${conv_usdc:.2f}")
print(f"Total markets with conversions but no trades: {conv_only}")
