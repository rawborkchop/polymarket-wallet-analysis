"""Test: does the updated calculator fix the PnL for 0xf2e346ab?"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Market
from wallet_analysis.calculators.pnl_calculator import AvgCostBasisCalculator

w = Wallet.objects.get(id=8)

# Check if neg_risk data is populated
nr_count = Market.objects.filter(neg_risk=True).count()
print(f"Markets with neg_risk=True: {nr_count}")
if nr_count == 0:
    print("WARNING: Run 'python manage.py populate_neg_risk --wallet-id 8' first!")
    sys.exit(1)

# Build groups to verify
calc = AvgCostBasisCalculator(w.id)
groups = calc._build_neg_risk_groups(w)
print(f"Neg-risk groups: {len(groups)}")
total_children = sum(len(v) for v in groups.values())
print(f"Total children in groups: {total_children}")

# Show a sample group
for gid, mids in list(groups.items())[:3]:
    titles = [Market.objects.get(id=mid).title[:50] for mid in mids[:5]]
    print(f"  Group {gid[:20]}...: {len(mids)} markets")
    for t in titles:
        print(f"    - {t}")

# Run calculator
print(f"\n{'='*60}")
print(f"RUNNING CALCULATOR")
print(f"{'='*60}")

for period in ['ALL', '1M', '1W', '1D']:
    result = calc.calculate(period=period)
    print(f"\n{period}:")
    print(f"  total_pnl (all-time): ${result['total_pnl']:.2f}")
    print(f"  period_pnl:           ${result['period_pnl']:.2f}")
    print(f"  totals: buys=${result['totals']['total_buys']:.0f} sells=${result['totals']['total_sells']:.0f} redeems=${result['totals']['total_redeems']:.0f}")

print(f"\nPolymarket official ALL: $25,000")
print(f"Gap: ${25000 - result['total_pnl']:.2f}")
