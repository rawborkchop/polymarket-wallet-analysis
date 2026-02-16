import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity

w = Wallet.objects.get(address__startswith='0xbdcd')
redeems = Activity.objects.filter(wallet=w, activity_type='REDEEM')
total = redeems.count()
no_trades = 0
total_usdc_no_trades = 0

for r in redeems:
    tc = Trade.objects.filter(wallet=w, market_id=r.market_id).count()
    if tc == 0:
        no_trades += 1
        total_usdc_no_trades += float(r.usdc_size)

print(f'Total redeems: {total}')
print(f'Redeems without trades: {no_trades}')
print(f'USDC in redeems without trades: ${total_usdc_no_trades:,.2f}')

# Those without trades came from SPLITs likely
no_trade_redeems = [r for r in redeems if Trade.objects.filter(wallet=w, market_id=r.market_id).count() == 0]
for r in no_trade_redeems[:3]:
    splits = Activity.objects.filter(wallet=w, market_id=r.market_id, activity_type='SPLIT').count()
    print(f'  market_id={r.market_id}: splits={splits}, usdc={r.usdc_size}')
