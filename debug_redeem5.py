"""Check if we're missing trades or activities by comparing API totals."""
import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

import requests
from wallet_analysis.models import Wallet, Trade, Activity

w = Wallet.objects.get(address__startswith='0xbdcd')
address = w.address

# Check activity API - count all
print("Checking Activity API...")
activity_types = ['REDEEM', 'SPLIT', 'MERGE', 'REWARD']
for atype in activity_types:
    url = f"https://data-api.polymarket.com/activity?user={address}&type={atype}&limit=1"
    r = requests.get(url, timeout=30)
    data = r.json()
    db_count = Activity.objects.filter(wallet=w, activity_type=atype).count()
    # The API doesn't return total count easily, but we can check if our DB has all
    print(f"  {atype}: DB has {db_count}, API sample: {len(data)} items returned")

# Check trade count via profit-loss endpoint  
print("\nChecking profit-loss endpoint...")
url = f"https://data-api.polymarket.com/profit-loss?address={address}"
r = requests.get(url, timeout=30)
if r.status_code == 200:
    data = r.json()
    print(f"  Entries: {len(data)}")
    if data:
        total_realized = sum(float(d.get('realizedPnl', 0)) for d in data)
        total_initial = sum(float(d.get('initialValue', 0)) for d in data)
        total_current = sum(float(d.get('currentValue', 0)) for d in data)
        print(f"  Sum realizedPnl: ${total_realized:,.2f}")
        print(f"  Sum initialValue: ${total_initial:,.2f}")
        print(f"  Sum currentValue: ${total_current:,.2f}")
        # Show a few entries
        for d in data[:3]:
            print(f"  Sample: {d.get('conditionId','')[:20]}... realized={d.get('realizedPnl')} initial={d.get('initialValue')} current={d.get('currentValue')}")
else:
    print(f"  Status: {r.status_code}")

# Also check: how many trades does the API have?
print("\nChecking trades API count...")
url = f"https://data-api.polymarket.com/trades?user={address}&limit=1&offset=0"
r = requests.get(url, timeout=30)
data = r.json()
print(f"  DB trades: {Trade.objects.filter(wallet=w).count()}")
# Try to get total by fetching last page
url2 = f"https://data-api.polymarket.com/trades?user={address}&limit=1&offset=99999"
r2 = requests.get(url2, timeout=30)
print(f"  API response at offset 99999: {len(r2.json())} items")
