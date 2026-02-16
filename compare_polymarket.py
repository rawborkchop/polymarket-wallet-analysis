"""Compare our per-position PnL vs Polymarket's positions API."""
import os, django, json
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from wallet_analysis.models import Wallet
from wallet_analysis.calculators.cost_basis_calculator import CostBasisPnLCalculator
import urllib.request

wallet = Wallet.objects.get(id=7)
address = wallet.address

# Fetch Polymarket positions
url = f"https://data-api.polymarket.com/positions?user={address}&sizeThreshold=0"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as resp:
    pm_positions = json.loads(resp.read())

print(f"Polymarket positions: {len(pm_positions)}")
pm_total_realized = sum(float(p.get('realizedPnl', 0)) for p in pm_positions)
pm_total_cash = sum(float(p.get('cashPnl', 0)) for p in pm_positions)
print(f"Polymarket sum realizedPnl: ${pm_total_realized:.2f}")
print(f"Polymarket sum cashPnl: ${pm_total_cash:.2f}")

# Build lookup by asset
pm_by_asset = {}
for p in pm_positions:
    pm_by_asset[p['asset']] = p

# Our calculation
calc = CostBasisPnLCalculator()
result = calc.calculate(wallet)
our_positions = result.get('positions', [])

print(f"\nOur positions: {len(our_positions)}")
print(f"Our total realized PnL: ${result['total_realized_pnl']:.2f}")

# Compare matching positions
matches = 0
total_our = Decimal('0')
total_pm = Decimal('0')
big_diffs = []

for pos in our_positions:
    asset = pos.get('asset', '')
    if asset in pm_by_asset:
        matches += 1
        pm = pm_by_asset[asset]
        our_pnl = float(pos.get('realized_pnl', 0))
        pm_pnl = float(pm.get('realizedPnl', 0))
        diff = our_pnl - pm_pnl
        if abs(diff) > 10:
            big_diffs.append({
                'asset': asset[:20],
                'market': pos.get('market_id'),
                'our_pnl': our_pnl,
                'pm_pnl': pm_pnl,
                'diff': diff,
                'title': pm.get('title', '')[:60]
            })

print(f"Matching assets: {matches}")
print(f"\nPositions with >$10 PnL difference: {len(big_diffs)}")
for d in sorted(big_diffs, key=lambda x: abs(x['diff']), reverse=True)[:20]:
    print(f"  Market {d['market']}: ours=${d['our_pnl']:.2f} PM=${d['pm_pnl']:.2f} diff=${d['diff']:.2f} | {d['title']}")
