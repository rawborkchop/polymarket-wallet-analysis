"""Verify: does PM 'month' mean calendar month or rolling 30 days?"""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from datetime import datetime, date, timedelta
from wallet_analysis.models import Wallet, Trade, Activity
from collections import defaultdict
import pytz

w = Wallet.objects.get(id=7)

# Build daily cash flow
daily_cf = defaultdict(Decimal)
for t in Trade.objects.filter(wallet=w).iterator():
    d = t.datetime.date()
    vol = Decimal(str(t.price)) * Decimal(str(t.size))
    daily_cf[d] += vol if t.side == 'SELL' else -vol

for a in Activity.objects.filter(wallet=w).iterator():
    d = datetime.fromtimestamp(int(a.timestamp), tz=pytz.UTC).date()
    usdc = Decimal(str(a.usdc_size or 0))
    if a.activity_type in ('REDEEM', 'MERGE', 'REWARD'):
        daily_cf[d] += usdc
    elif a.activity_type == 'SPLIT':
        daily_cf[d] -= usdc

dates = sorted(daily_cf.keys())
cumulative = {}
running = Decimal('0')
for d in dates:
    running += daily_cf[d]
    cumulative[d] = running

def cum_at(target):
    best = None
    for d in dates:
        if d <= target:
            best = d
    return cumulative.get(best, Decimal('0')) if best else Decimal('0')

today = date(2026, 2, 16)  # when PM was queried

# Try different "month" definitions
windows = {
    'Calendar Feb (Feb 1 - Feb 15)': (date(2026, 1, 31), date(2026, 2, 15)),
    'Calendar Feb (Feb 1 - Feb 16)': (date(2026, 1, 31), date(2026, 2, 16)),
    'Rolling 30d (Jan 17 - Feb 15)': (date(2026, 1, 16), date(2026, 2, 15)),
    'Rolling 30d (Jan 17 - Feb 16)': (date(2026, 1, 16), date(2026, 2, 16)),
    'Last 28d': (date(2026, 1, 19), date(2026, 2, 15)),
    'Calendar Jan (full)': (date(2025, 12, 31), date(2026, 1, 31)),
    'Calendar Jan (Jan 1-31)': (date(2025, 12, 31), date(2026, 1, 31)),
}

print("PM official month: $710.14")
print("PM official week: $0.04")
print(f"\n{'Window':<40} {'PnL':>12} {'Diff from PM':>12}")
print("-" * 65)
for label, (start, end) in windows.items():
    pnl = cum_at(end) - cum_at(start)
    diff = pnl - Decimal('710.14')
    print(f"{label:<40} ${pnl:>10.2f} ${diff:>10.2f}")

# Week windows
print(f"\n{'Week Window':<40} {'PnL':>12}")
print("-" * 55)
for days_back in [7, 6, 5, 8, 9, 10]:
    s = date(2026, 2, 15) - timedelta(days=days_back)
    e = date(2026, 2, 15)
    pnl = cum_at(e) - cum_at(s)
    print(f"{'Last ' + str(days_back) + 'd (' + str(s) + ' - ' + str(e) + ')':<40} ${pnl:>10.2f}")

# What about just the last few days?
print(f"\n=== DAILY PNL (last 14 days) ===")
for d in sorted(daily_cf.keys())[-14:]:
    print(f"{d}: ${daily_cf[d]:>10.2f} (cum: ${cumulative[d]:.2f})")
