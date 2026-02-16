import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity
from decimal import Decimal

w = Wallet.objects.get(address__startswith='0xbdcd')

# Check a few redeems
redeems = Activity.objects.filter(wallet=w, activity_type='REDEEM').order_by('timestamp')[:5]
for r in redeems:
    print(f'REDEEM: market_id={r.market_id}, asset={r.asset}, outcome={r.outcome}')
    print(f'  size={r.size}, usdc_size={r.usdc_size}')
    # Check if there are trades for this market
    market_trades = Trade.objects.filter(wallet=w, market_id=r.market_id).count()
    print(f'  Trades for this market: {market_trades}')
    if market_trades > 0:
        t = Trade.objects.filter(wallet=w, market_id=r.market_id).first()
        print(f'  Sample trade asset: {t.asset}, outcome: {t.outcome}')
    print()

# Also check: how does the Activity store market_id vs condition_id
print("=== Activity fields ===")
a = redeems[0]
print(f'market: {a.market_id}, type(market): {type(a.market_id)}')
# Check if market is FK or string
print(f'market field: {Activity._meta.get_field("market")}')

# Trades
t = Trade.objects.filter(wallet=w).first()
print(f'\n=== Trade fields ===')
print(f'market: {t.market_id}, asset: {t.asset}')
print(f'market field: {Trade._meta.get_field("market")}')
