"""Check if we're missing trades - our volume is $204K vs PM's $773K"""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from wallet_analysis.models import Wallet, Trade
from collections import Counter

w = Wallet.objects.get(id=7)
trades = Trade.objects.filter(wallet=w).order_by('datetime')

print(f"Total trades: {trades.count()}")
print(f"First: {trades.first().datetime}")
print(f"Last: {trades.last().datetime}")

# Volume by month
monthly = {}
for t in trades:
    month = t.datetime.strftime('%Y-%m')
    if month not in monthly:
        monthly[month] = {'buys': 0, 'sells': 0, 'buy_vol': Decimal('0'), 'sell_vol': Decimal('0')}
    side = t.side
    vol = Decimal(str(t.price)) * Decimal(str(t.size))
    monthly[month][f'{side.lower()}s'] += 1
    monthly[month][f'{side.lower()}_vol'] += vol

print("\n=== VOLUME BY MONTH ===")
total_vol = Decimal('0')
for month in sorted(monthly.keys()):
    d = monthly[month]
    mv = d['buy_vol'] + d['sell_vol']
    total_vol += mv
    print(f"{month}: buys={d['buys']} sells={d['sells']} vol=${mv:.0f}")

print(f"\nTotal calculated volume: ${total_vol:.2f}")
print(f"PM reported volume: $773,199.66")
print(f"Missing volume: ${Decimal('773199.66') - total_vol:.2f}")

# Check: are there trades with 0 value?
zero_trades = trades.filter(price=0)
print(f"\nTrades with price=0: {zero_trades.count()}")

# PM volume likely includes BOTH sides of each trade (buy volume + sell volume separately)
# Or it could be total notional including activities
from wallet_analysis.models import Activity
acts = Activity.objects.filter(wallet=w)
act_vol = sum(Decimal(str(a.usdc_size or 0)) for a in acts)
print(f"\nActivity USDC volume: ${act_vol:.2f}")
print(f"Trade + Activity volume: ${total_vol + act_vol:.2f}")

# Maybe PM counts size (shares) not notional?
total_size = sum(Decimal(str(t.size)) for t in trades)
print(f"\nTotal trade size (shares): {total_size:.2f}")
