import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()
from wallet_analysis.models import Wallet
from wallet_analysis.calculators.cost_basis_calculator import CostBasisPnLCalculator

w = Wallet.objects.get(id=7)
print(f"Wallet: {w.name}")
print(f"data_start: {w.data_start_date}")
print(f"data_end: {w.data_end_date}")

calc = CostBasisPnLCalculator()
result = calc.calculate(w)
print(f"\nCost Basis PnL: ${result.get('total_realized_pnl', 'N/A'):.2f}")
print(f"Positions: {len(result.get('positions', []))}")

# Also check top 5 positions by PnL
positions = result.get('positions', [])
positions.sort(key=lambda p: abs(p.get('realized_pnl', 0)), reverse=True)
print("\nTop 5 positions by PnL:")
for p in positions[:5]:
    print(f"  Market {p.get('market_id')}: ${p.get('realized_pnl', 0):.2f} (bought={p.get('total_bought', 0):.0f}, sold={p.get('total_sold', 0):.0f})")
