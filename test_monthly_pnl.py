"""Test cash flow PnL by month and try conversion/reward combos"""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from datetime import datetime
from wallet_analysis.models import Wallet, Trade, Activity

w = Wallet.objects.get(id=7)

# Get all trades and activities with timestamps
trades = list(Trade.objects.filter(wallet=w).order_by('datetime'))
activities = list(Activity.objects.filter(wallet=w).order_by('timestamp'))

# Build monthly buckets
monthly = {}

for t in trades:
    month = t.datetime.strftime('%Y-%m')
    if month not in monthly:
        monthly[month] = {'buy': Decimal('0'), 'sell': Decimal('0'), 'redeem': Decimal('0'),
                         'merge': Decimal('0'), 'split': Decimal('0'), 'reward': Decimal('0'),
                         'conversion': Decimal('0')}
    vol = Decimal(str(t.price)) * Decimal(str(t.size))
    if t.side == 'BUY':
        monthly[month]['buy'] += vol
    else:
        monthly[month]['sell'] += vol

for a in activities:
    ts = datetime.fromtimestamp(int(a.timestamp))
    month = ts.strftime('%Y-%m')
    if month not in monthly:
        monthly[month] = {'buy': Decimal('0'), 'sell': Decimal('0'), 'redeem': Decimal('0'),
                         'merge': Decimal('0'), 'split': Decimal('0'), 'reward': Decimal('0'),
                         'conversion': Decimal('0')}
    usdc = Decimal(str(a.usdc_size or 0))
    monthly[month][a.activity_type.lower()] += usdc

# Fetch leaderboard monthly PnL
import urllib.request, json
url = f"https://data-api.polymarket.com/v1/leaderboard?timePeriod=month&orderBy=PNL&limit=1&offset=0&category=overall&user={w.address}"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as resp:
    pm_month = json.loads(resp.read())
pm_month_pnl = float(pm_month[0]['pnl']) if pm_month else 0

url2 = f"https://data-api.polymarket.com/v1/leaderboard?timePeriod=all&orderBy=PNL&limit=1&offset=0&category=overall&user={w.address}"
req2 = urllib.request.Request(url2, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req2) as resp2:
    pm_all = json.loads(resp2.read())
pm_all_pnl = float(pm_all[0]['pnl']) if pm_all else 0

print(f"PM official ALL: ${pm_all_pnl:.2f}")
print(f"PM official MONTH: ${pm_month_pnl:.2f}")

# Print monthly breakdown with different formulas
print(f"\n{'Month':<10} {'V2 (no rw/cv)':<15} {'V3 (+reward)':<15} {'V4 (+rw+conv)':<15} {'V5 (+rw+conv/2)':<15}")
print("-" * 70)

cumV2 = cumV3 = cumV4 = cumV5 = Decimal('0')
for month in sorted(monthly.keys()):
    d = monthly[month]
    v2 = d['sell'] + d['redeem'] + d['merge'] - d['buy'] - d['split']
    v3 = v2 + d['reward']
    v4 = v3 + d['conversion']
    v5 = v3 + d['conversion'] / 2  # maybe half?
    
    cumV2 += v2; cumV3 += v3; cumV4 += v4; cumV5 += v5
    print(f"{month:<10} ${v2:>12.2f} ${v3:>12.2f} ${v4:>12.2f} ${v5:>12.2f}")

print("-" * 70)
print(f"{'TOTAL':<10} ${cumV2:>12.2f} ${cumV3:>12.2f} ${cumV4:>12.2f} ${cumV5:>12.2f}")
print(f"{'TARGET':<10} ${Decimal(str(pm_all_pnl)):>12.2f}")

# Last month specifically (Jan 16 - Feb 15 2026)
last_month_months = ['2026-01', '2026-02']
lm = {'buy': Decimal('0'), 'sell': Decimal('0'), 'redeem': Decimal('0'),
      'merge': Decimal('0'), 'split': Decimal('0'), 'reward': Decimal('0'), 'conversion': Decimal('0')}

# Actually need exact 30-day window, not calendar months
from datetime import date, timedelta
end = date(2026, 2, 15)
start = end - timedelta(days=30)

for t in trades:
    if start <= t.datetime.date() <= end:
        vol = Decimal(str(t.price)) * Decimal(str(t.size))
        if t.side == 'BUY':
            lm['buy'] += vol
        else:
            lm['sell'] += vol

for a in activities:
    ts = datetime.fromtimestamp(int(a.timestamp)).date()
    if start <= ts <= end:
        usdc = Decimal(str(a.usdc_size or 0))
        lm[a.activity_type.lower()] += usdc

print(f"\n=== LAST 30 DAYS ({start} to {end}) ===")
for k, v in lm.items():
    print(f"  {k}: ${v:.2f}")

v2_30 = lm['sell'] + lm['redeem'] + lm['merge'] - lm['buy'] - lm['split']
v3_30 = v2_30 + lm['reward']
v4_30 = v3_30 + lm['conversion']
print(f"\n  V2 (no rw/cv): ${v2_30:.2f}")
print(f"  V3 (+reward): ${v3_30:.2f}")
print(f"  V4 (+rw+conv): ${v4_30:.2f}")
print(f"  PM official month: ${pm_month_pnl:.2f}")
