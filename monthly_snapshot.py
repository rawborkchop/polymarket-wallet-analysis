"""
Hypothesis: PM monthly PnL = cumulative_cashflow_pnl(now) - cumulative_cashflow_pnl(30_days_ago)
Our cash flow all-time = $19,283 which is $890 short.
If the gap is consistent over time, the monthly DIFFERENCE should still be accurate.

Let's compute cumulative cash flow at daily granularity and check monthly diffs.
"""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from datetime import datetime, date, timedelta
from wallet_analysis.models import Wallet, Trade, Activity
from collections import defaultdict
import pytz

w = Wallet.objects.get(id=7)

# Build daily cash flow deltas efficiently
daily_cf = defaultdict(Decimal)

for t in Trade.objects.filter(wallet=w).iterator():
    d = t.datetime.date()
    vol = Decimal(str(t.price)) * Decimal(str(t.size))
    if t.side == 'BUY':
        daily_cf[d] -= vol
    else:
        daily_cf[d] += vol

for a in Activity.objects.filter(wallet=w).iterator():
    d = datetime.fromtimestamp(int(a.timestamp), tz=pytz.UTC).date()
    usdc = Decimal(str(a.usdc_size or 0))
    if a.activity_type in ('REDEEM', 'MERGE', 'REWARD'):
        daily_cf[d] += usdc
    elif a.activity_type == 'SPLIT':
        daily_cf[d] -= usdc
    # CONVERSION excluded

# Build cumulative
dates = sorted(daily_cf.keys())
cumulative = {}
running = Decimal('0')
for d in dates:
    running += daily_cf[d]
    cumulative[d] = running

print(f"First date: {dates[0]}, Last date: {dates[-1]}")
print(f"Final cumulative PnL: ${running:.2f} (PM official: $20,172.77)")

# Monthly diffs (rolling 30 days)
end = dates[-1]
periods = {
    '30d': end - timedelta(days=30),
    '7d': end - timedelta(days=7),
    '1d': end - timedelta(days=1),
}

# Find nearest date <= target
def nearest_before(target):
    best = None
    for d in dates:
        if d <= target:
            best = d
    return best

print(f"\n=== PERIOD PNL (cumulative diff method) ===")
for label, start in periods.items():
    start_d = nearest_before(start)
    if start_d:
        diff = cumulative[end] - cumulative[start_d]
        print(f"{label}: ${diff:.2f} (start={start_d}, cum_start=${cumulative[start_d]:.2f})")
    else:
        print(f"{label}: no data before {start}")

# PM official for comparison
import urllib.request, json
for period in ['all', 'month', 'week', 'day']:
    url = f"https://data-api.polymarket.com/v1/leaderboard?timePeriod={period}&orderBy=PNL&limit=1&offset=0&category=overall&user={w.address}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        if data:
            print(f"PM {period}: ${float(data[0]['pnl']):.2f}")
        else:
            print(f"PM {period}: not found")
    except Exception as e:
        print(f"PM {period}: error {e}")

# Monthly calendar diffs
print(f"\n=== MONTHLY CALENDAR DIFFS ===")
months = sorted(set(d.strftime('%Y-%m') for d in dates))
prev_cum = Decimal('0')
for m in months:
    month_dates = [d for d in dates if d.strftime('%Y-%m') == m]
    end_cum = cumulative[month_dates[-1]]
    diff = end_cum - prev_cum
    print(f"{m}: ${diff:>10.2f} (cumulative end: ${end_cum:.2f})")
    prev_cum = end_cum
