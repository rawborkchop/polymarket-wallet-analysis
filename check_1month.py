"""Check what our calculator gives for 1-month PnL vs Polymarket's $1,282."""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from datetime import date, timedelta
from decimal import Decimal
from wallet_analysis.models import Wallet, Trade, Activity
from wallet_analysis.calculators.cost_basis_calculator import CostBasisPnLCalculator

wallet = Wallet.objects.get(id=7)

# Last 30 days
end_date = date(2026, 2, 15)
start_date = end_date - timedelta(days=30)
print(f"Period: {start_date} to {end_date}")

# Method 1: Use calculate_filtered
calc = CostBasisPnLCalculator()
filtered = calc.calculate_filtered(wallet, start_date, end_date)
print(f"\nFiltered PnL (cost basis, last 30d): ${filtered.get('total_realized_pnl', 0):.2f}")

# Method 2: Count trades in that period
trades_in_period = Trade.objects.filter(wallet=wallet, datetime__date__gte=start_date, datetime__date__lte=end_date)
activities_in_period = Activity.objects.filter(wallet=wallet, timestamp__gte=int(start_date.strftime('%s')) if hasattr(start_date, 'strftime') else 0)
print(f"Trades in period: {trades_in_period.count()}")

# Method 3: ALL time for comparison
full = calc.calculate(wallet)
print(f"\nALL-TIME PnL (cost basis): ${full.get('total_realized_pnl', 0):.2f}")

# Method 4: Simple cash flow for period
from wallet_analysis.calculators.pnl_calculator import PnLCalculator
pnl_calc = PnLCalculator()
cash_result = pnl_calc.calculate_for_period(wallet, start_date, end_date)
if cash_result:
    print(f"Cash flow PnL (last 30d): ${cash_result.get('pnl', 0):.2f}")
else:
    print("Cash flow calc returned None")

print(f"\n=== TARGET: $1,282.17 (Polymarket official 1M) ===")
