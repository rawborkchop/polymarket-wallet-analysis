import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()
from wallet_analysis.models import Trade, Activity, Wallet
w = Wallet.objects.get(id=7)
print(f'Wallet: {w.name}')
print(f'data_start: {w.data_start_date}')
print(f'data_end: {w.data_end_date}')
trades = Trade.objects.filter(wallet=w)
print(f'Total trades: {trades.count()}')
print(f'First trade: {trades.order_by("datetime").first().datetime}')
print(f'Last trade: {trades.order_by("datetime").last().datetime}')
acts = Activity.objects.filter(wallet=w)
print(f'Total activities: {acts.count()}')
print(f'First activity: {acts.order_by("timestamp").first().timestamp}')
print(f'Last activity: {acts.order_by("timestamp").last().timestamp}')
