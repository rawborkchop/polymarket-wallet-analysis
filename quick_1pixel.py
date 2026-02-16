import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()
from wallet_analysis.calculators.pnl_calculator import AvgCostBasisCalculator
r = AvgCostBasisCalculator(7).calculate('ALL')
print(f"1pixel ALL: ${r['total_pnl']:.2f} (expected: $20,121.57)")
