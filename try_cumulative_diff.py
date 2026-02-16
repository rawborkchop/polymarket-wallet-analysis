"""
Hypothesis: PM monthly PnL = ALL-TIME PnL at end of period - ALL-TIME PnL at start of period
This is the simplest definition: how much did total PnL grow in the last 30 days?

If correct: monthly = current_all_time - all_time_30_days_ago
"""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from datetime import datetime, date, timedelta
from wallet_analysis.models import Wallet, Trade, Activity

w = Wallet.objects.get(id=7)
end = date(2026, 2, 15)
start = end - timedelta(days=30)

# Calculate ALL-TIME cash flow PnL up to different dates
trades = list(Trade.objects.filter(wallet=w).order_by('datetime'))
activities = list(Activity.objects.filter(wallet=w).order_by('timestamp'))

def cashflow_pnl_up_to(cutoff_date):
    """V3 cash flow PnL for all events up to cutoff_date"""
    pnl = Decimal('0')
    for t in trades:
        if t.datetime.date() > cutoff_date:
            continue
        vol = Decimal(str(t.price)) * Decimal(str(t.size))
        if t.side == 'BUY':
            pnl -= vol
        else:
            pnl += vol
    for a in activities:
        ts = datetime.fromtimestamp(int(a.timestamp)).date()
        if ts > cutoff_date:
            continue
        usdc = Decimal(str(a.usdc_size or 0))
        if a.activity_type in ('REDEEM', 'MERGE', 'REWARD'):
            pnl += usdc
        elif a.activity_type == 'SPLIT':
            pnl -= usdc
        # CONVERSION ignored
    return pnl

pnl_end = cashflow_pnl_up_to(end)
pnl_start = cashflow_pnl_up_to(start)
diff = pnl_end - pnl_start

print(f"ALL-TIME PnL up to {end}: ${pnl_end:.2f}")
print(f"ALL-TIME PnL up to {start}: ${pnl_start:.2f}")
print(f"Difference (monthly): ${diff:.2f}")
print(f"PM official month: $710.14")
print(f"PM official all: $20,172.77")

# Also try weekly
week_start = end - timedelta(days=7)
pnl_week_start = cashflow_pnl_up_to(week_start)
week_diff = pnl_end - pnl_week_start

print(f"\nALL-TIME PnL up to {week_start}: ${pnl_week_start:.2f}")
print(f"Weekly diff: ${week_diff:.2f}")
print(f"PM official week: $0.04")

# Try specific months
months = [
    (date(2025, 2, 1), date(2025, 2, 28)),
    (date(2025, 3, 1), date(2025, 3, 31)),
    (date(2025, 6, 1), date(2025, 6, 30)),
    (date(2025, 7, 1), date(2025, 7, 31)),
    (date(2025, 12, 1), date(2025, 12, 31)),
    (date(2026, 1, 1), date(2026, 1, 31)),
]

print("\n=== CUMULATIVE DIFF BY MONTH ===")
for ms, me in months:
    p_end = cashflow_pnl_up_to(me)
    p_start = cashflow_pnl_up_to(ms - timedelta(days=1))
    print(f"{ms.strftime('%Y-%m')}: ${p_end - p_start:.2f} (cumulative at end: ${p_end:.2f})")
