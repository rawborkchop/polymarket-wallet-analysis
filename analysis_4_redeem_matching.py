"""Analysis 4: REDEEM matching quality.
Are redeems being matched to the right positions? 
Count unmatched redeems and their USDC impact."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity
from decimal import Decimal
from collections import defaultdict

w = Wallet.objects.get(id=8)

# Get all redeems
redeems = Activity.objects.filter(wallet=w, activity_type='REDEEM').order_by('timestamp')
print(f"Total redeems: {redeems.count()}")

# Check redeems where there are NO buy trades in that market
no_buy_market = 0
no_buy_value = Decimal(0)
has_buy_value = Decimal(0)

redeem_by_market = defaultdict(list)
for r in redeems:
    redeem_by_market[r.market_id].append(r)

for mid, rlist in redeem_by_market.items():
    buy_count = Trade.objects.filter(wallet=w, market_id=mid, side='BUY').count()
    rv = sum(Decimal(str(r.usdc_size or 0)) for r in rlist)
    if buy_count == 0:
        no_buy_market += 1
        no_buy_value += rv
        if rv > 100:
            title = rlist[0].title or f"Market#{mid}"
            print(f"  NO BUYS: {title[:60]} redeems={len(rlist)} value=${rv:.2f}")
    else:
        has_buy_value += rv

print(f"\nRedeems in markets with NO buys: {no_buy_market} markets, ${no_buy_value:.2f}")
print(f"Redeems in markets with buys: {len(redeem_by_market) - no_buy_market} markets, ${has_buy_value:.2f}")

# Check redeems with empty asset/outcome (the known API bug)
empty_asset = redeems.filter(asset='').count()
empty_outcome = redeems.filter(outcome='').count()
print(f"\nRedeems with empty asset: {empty_asset}/{redeems.count()}")
print(f"Redeems with empty outcome: {empty_outcome}/{redeems.count()}")

# Winner vs loser redeems
winner_value = Decimal(0)
loser_count = 0
winner_count = 0
for r in redeems:
    usdc = Decimal(str(r.usdc_size or 0))
    if usdc > 0:
        winner_value += usdc
        winner_count += 1
    else:
        loser_count += 1

print(f"\nWinner redeems: {winner_count} (${winner_value:.2f})")
print(f"Loser redeems: {loser_count} ($0)")
print(f"Total: {winner_count + loser_count}")
