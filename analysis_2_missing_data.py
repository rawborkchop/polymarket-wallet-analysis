"""Analysis 2: Are we missing trades/activities?
Compare our data counts with what the API says. Check for gaps in timestamp pagination."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

import requests
from wallet_analysis.models import Wallet, Trade, Activity
from collections import defaultdict

w = Wallet.objects.get(id=8)
addr = w.address

# Our counts
our_trades = Trade.objects.filter(wallet=w).count()
our_activities = Activity.objects.filter(wallet=w).count()
print(f"Our DB: {our_trades} trades, {our_activities} activities")

# Check trades API with offset pagination (different from activity API)
# Count total trades available
print("\n=== Checking /trades endpoint ===")
total_api_trades = 0
offset = 0
while True:
    r = requests.get(f'https://data-api.polymarket.com/trades?user={addr}&limit=500&offset={offset}', timeout=15)
    if r.status_code != 200:
        print(f"  Error at offset {offset}: {r.status_code}")
        break
    batch = r.json()
    if not batch:
        break
    total_api_trades += len(batch)
    offset += len(batch)
    if len(batch) < 500:
        break
    if offset >= 15000:  # Safety limit
        print(f"  Hit safety limit at offset {offset}")
        break

print(f"API /trades: {total_api_trades} trades (offset pagination)")
print(f"Difference: {total_api_trades - our_trades}")

# Check for timestamp gaps in our data
print("\n=== Checking timestamp continuity ===")
trades = Trade.objects.filter(wallet=w).order_by('timestamp').values_list('timestamp', flat=True)
ts_list = list(trades)
if ts_list:
    max_gap = 0
    gap_at = 0
    for i in range(1, len(ts_list)):
        gap = ts_list[i] - ts_list[i-1]
        if gap > max_gap:
            max_gap = gap
            gap_at = i
    print(f"  Timestamp range: {ts_list[0]} -> {ts_list[-1]}")
    print(f"  Max gap: {max_gap} seconds ({max_gap/3600:.1f} hours) at index {gap_at}")
    from datetime import datetime
    print(f"  Gap at: {datetime.fromtimestamp(ts_list[gap_at-1])} -> {datetime.fromtimestamp(ts_list[gap_at])}")

# Check activity counts by type from API
print("\n=== Checking /activity endpoint counts ===")
# Fetch first and last batches to see range
r = requests.get(f'https://data-api.polymarket.com/activity?user={addr}&limit=1', timeout=10)
if r.status_code == 200 and r.json():
    latest = r.json()[0]
    print(f"Latest activity: type={latest.get('activity_type','')} ts={latest.get('timestamp','')}")

# Fetch with start=0 to get oldest
r2 = requests.get(f'https://data-api.polymarket.com/activity?user={addr}&limit=1&start=0', timeout=10)
if r2.status_code == 200 and r2.json():
    oldest = r2.json()[0]
    print(f"Oldest activity: type={oldest.get('activity_type','')} ts={oldest.get('timestamp','')}")

# Count by type in our DB
print("\n=== Our activity breakdown ===")
for atype in ['TRADE', 'REDEEM', 'SPLIT', 'MERGE', 'REWARD', 'CONVERSION']:
    if atype == 'TRADE':
        count = Trade.objects.filter(wallet=w).count()
    else:
        count = Activity.objects.filter(wallet=w, activity_type=atype).count()
    print(f"  {atype}: {count}")
