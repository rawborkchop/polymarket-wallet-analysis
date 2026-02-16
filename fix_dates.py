import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()
from wallet_analysis.models import Wallet, Trade, Activity
from django.db.models import Min, Max

w = Wallet.objects.get(id=7)
print(f"BEFORE: start={w.data_start_date}, end={w.data_end_date}")

trade_dates = Trade.objects.filter(wallet=w).aggregate(min_date=Min('datetime'), max_date=Max('datetime'))
print(f"Trade range: {trade_dates['min_date']} to {trade_dates['max_date']}")

if trade_dates['min_date']:
    w.data_start_date = trade_dates['min_date'].date()
if trade_dates['max_date']:
    w.data_end_date = trade_dates['max_date'].date()
w.save()
print(f"AFTER: start={w.data_start_date}, end={w.data_end_date}")
