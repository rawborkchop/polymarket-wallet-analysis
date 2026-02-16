"""Verify 1pixel PnL is unchanged after neg-risk changes."""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.calculators.pnl_calculator import AvgCostBasisCalculator

calc = AvgCostBasisCalculator(7)  # 1pixel
r = calc.calculate(period='ALL')
print(f"1pixel ALL: total_pnl=${r['total_pnl']:.2f}, period_pnl=${r['period_pnl']:.2f}")
print(f"Expected: ~$20,121 (before was $20,121.57)")

# Check neg-risk groups for 1pixel
groups = calc._build_neg_risk_groups.__func__(calc, 
    __import__('wallet_analysis.models', fromlist=['Wallet']).Wallet.objects.get(id=7))
print(f"Neg-risk groups for 1pixel: {len(groups)}")
