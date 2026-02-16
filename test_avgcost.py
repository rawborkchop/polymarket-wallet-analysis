import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
import django
django.setup()

from wallet_analysis.calculators.pnl_calculator import AvgCostBasisCalculator
calc = AvgCostBasisCalculator(wallet_id=7)
result = calc.calculate(period='ALL')
print('Keys:', list(result.keys()))
print('total_pnl:', result.get('total_pnl'))
print('period_pnl:', result.get('period_pnl'))

result_1m = calc.calculate(period='1M')
print('\n1M period_pnl:', result_1m.get('period_pnl'))
