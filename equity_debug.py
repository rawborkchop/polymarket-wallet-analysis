"""Debug negative balances and unmatched splits/redeems."""
import sys, os, django
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from collections import defaultdict
from wallet_analysis.models import Trade, Activity

WALLET_ID = 7
ZERO = Decimal('0')

# Check: how many activities have asset field populated?
activities = Activity.objects.filter(wallet_id=WALLET_ID)
for atype in ['REDEEM', 'SPLIT', 'MERGE']:
    subset = activities.filter(activity_type=atype)
    with_asset = subset.exclude(asset='').count()
    without_asset = subset.filter(asset='').count()
    print(f"{atype}: {subset.count()} total, {with_asset} with asset, {without_asset} without asset")

# Check: splits without market
splits_no_market = activities.filter(activity_type='SPLIT', market__isnull=True).count()
splits_with_market = activities.filter(activity_type='SPLIT', market__isnull=False).count()
print(f"\nSPLIT: {splits_with_market} with market, {splits_no_market} without market")

# Check sample redeem
print("\nSample REDEEMs:")
for a in activities.filter(activity_type='REDEEM')[:5]:
    print(f"  market_id={a.market_id} asset='{a.asset}' outcome='{a.outcome}' size={a.size} usdc={a.usdc_size}")

print("\nSample SPLITs:")
for a in activities.filter(activity_type='SPLIT')[:5]:
    print(f"  market_id={a.market_id} asset='{a.asset}' outcome='{a.outcome}' size={a.size} usdc={a.usdc_size}")

# How many markets from splits have known assets in trades?
split_markets = set(activities.filter(activity_type='SPLIT', market__isnull=False).values_list('market_id', flat=True))
trade_markets = set(Trade.objects.filter(wallet_id=WALLET_ID, market__isnull=False).values_list('market_id', flat=True))
print(f"\nSplit markets: {len(split_markets)}")
print(f"Split markets also in trades: {len(split_markets & trade_markets)}")
print(f"Split markets NOT in trades: {len(split_markets - trade_markets)}")
