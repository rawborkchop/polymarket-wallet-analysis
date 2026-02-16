"""Compare per-position PnL: our calculator vs Polymarket API."""
import os, django, json, sys
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from wallet_analysis.models import Wallet
from wallet_analysis.calculators.cost_basis_calculator import CostBasisPnLCalculator
import urllib.request

wallet = Wallet.objects.get(id=7)
address = wallet.address

# 1. Fetch Polymarket positions
url = f"https://data-api.polymarket.com/positions?user={address}&sizeThreshold=0"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as resp:
    pm_positions = json.loads(resp.read())

print(f"=== Polymarket API ===")
print(f"Positions returned: {len(pm_positions)}")

pm_by_asset = {}
for p in pm_positions:
    pm_by_asset[p['asset']] = p

pm_sum_realized = sum(float(p.get('realizedPnl', 0)) for p in pm_positions)
pm_sum_cash = sum(float(p.get('cashPnl', 0)) for p in pm_positions)
pm_sum_initial = sum(float(p.get('initialValue', 0)) for p in pm_positions)
pm_sum_cur_val = sum(float(p.get('currentValue', 0)) for p in pm_positions)
print(f"sum(realizedPnl): ${pm_sum_realized:.2f}")
print(f"sum(cashPnl): ${pm_sum_cash:.2f}")
print(f"sum(initialValue): ${pm_sum_initial:.2f}")
print(f"sum(currentValue): ${pm_sum_cur_val:.2f}")
print(f"cashPnl + realizedPnl: ${pm_sum_cash + pm_sum_realized:.2f}")
print(f"cashPnl + realizedPnl + currentValue - initialValue: ${pm_sum_cash + pm_sum_realized + pm_sum_cur_val - pm_sum_initial:.2f}")

# 2. Our calculation
calc = CostBasisPnLCalculator()
result = calc.calculate(wallet)
our_positions = result.get('positions', [])

print(f"\n=== Our Calculator ===")
print(f"Positions: {len(our_positions)}")
print(f"total_realized_pnl: ${result['total_realized_pnl']:.2f}")
print(f"total_unrealized_pnl: ${result['total_unrealized_pnl']:.2f}")
print(f"total_pnl: ${result['total_pnl']:.2f}")
print(f"cash_flow_pnl: ${result['cash_flow_pnl']:.2f}")

our_by_asset = {}
for p in our_positions:
    our_by_asset[p['asset']] = p

# 3. Compare per-position
print(f"\n=== Per-Position Comparison ===")

# Assets in both
common_assets = set(pm_by_asset.keys()) & set(our_by_asset.keys())
only_pm = set(pm_by_asset.keys()) - set(our_by_asset.keys())
only_ours = set(our_by_asset.keys()) - set(pm_by_asset.keys())

print(f"Common assets: {len(common_assets)}")
print(f"Only in Polymarket: {len(only_pm)}")
print(f"Only in ours: {len(only_ours)}")

# Detailed comparison for common assets
diffs = []
for asset in common_assets:
    pm = pm_by_asset[asset]
    ours = our_by_asset[asset]
    
    our_rpnl = ours['realized_pnl']
    pm_rpnl = float(pm.get('realizedPnl', 0))
    
    our_bought = ours['total_bought']
    pm_bought = float(pm.get('totalBought', 0))
    
    our_avg = ours['avg_price']
    pm_avg = float(pm.get('avgPrice', 0))
    
    our_cost = ours['total_cost']
    pm_initial = float(pm.get('initialValue', 0))
    
    rpnl_diff = our_rpnl - pm_rpnl
    bought_diff = our_bought - pm_bought
    
    diffs.append({
        'asset': asset[:16],
        'title': pm.get('title', '')[:50],
        'outcome': pm.get('outcome', ''),
        'our_rpnl': our_rpnl,
        'pm_rpnl': pm_rpnl,
        'rpnl_diff': rpnl_diff,
        'our_bought': our_bought,
        'pm_bought': pm_bought,
        'bought_diff': bought_diff,
        'our_avg': our_avg,
        'pm_avg': pm_avg,
        'our_cost': our_cost,
        'pm_initial': pm_initial,
        'pm_cash': float(pm.get('cashPnl', 0)),
    })

# Sort by abs rpnl diff
diffs.sort(key=lambda x: abs(x['rpnl_diff']), reverse=True)

sum_our_rpnl_common = sum(d['our_rpnl'] for d in diffs)
sum_pm_rpnl_common = sum(d['pm_rpnl'] for d in diffs)
sum_pm_cash_common = sum(d['pm_cash'] for d in diffs)

print(f"\nCommon positions: our sum realizedPnl=${sum_our_rpnl_common:.2f}, PM sum realizedPnl=${sum_pm_rpnl_common:.2f}")
print(f"Diff in common: ${sum_our_rpnl_common - sum_pm_rpnl_common:.2f}")

print(f"\n--- Top 30 differences (by realizedPnl) ---")
for d in diffs[:30]:
    if abs(d['rpnl_diff']) < 0.01:
        continue
    print(f"  {d['outcome']:3s} | rpnl: ours={d['our_rpnl']:+9.2f} pm={d['pm_rpnl']:+9.2f} diff={d['rpnl_diff']:+9.2f} | bought: ours={d['our_bought']:.1f} pm={d['pm_bought']:.1f} | avg: ours={d['our_avg']:.4f} pm={d['pm_avg']:.4f} | {d['title']}")

# 4. Only-in-ours positions (historical/closed not in PM API)
print(f"\n=== Positions ONLY in our calculator (not in PM API) ===")
only_ours_pnl = 0
only_ours_list = []
for asset in only_ours:
    p = our_by_asset[asset]
    only_ours_pnl += p['realized_pnl']
    if abs(p['realized_pnl']) > 0.01:
        only_ours_list.append(p)

only_ours_list.sort(key=lambda x: abs(x['realized_pnl']), reverse=True)
print(f"Count: {len(only_ours)}, total realized PnL: ${only_ours_pnl:.2f}")
for p in only_ours_list[:30]:
    print(f"  asset={p['asset'][:16]}... mkt={p.get('market_id','?')[:16]} out={p['outcome']:3s} rpnl={p['realized_pnl']:+9.2f} bought={p['total_bought']:.1f} qty={p['quantity']:.1f}")

# 5. Only-in-PM positions
print(f"\n=== Positions ONLY in Polymarket API (not in ours) ===")
only_pm_rpnl = 0
only_pm_cash = 0
only_pm_list = []
for asset in only_pm:
    p = pm_by_asset[asset]
    rpnl = float(p.get('realizedPnl', 0))
    cash = float(p.get('cashPnl', 0))
    only_pm_rpnl += rpnl
    only_pm_cash += cash
    if abs(rpnl) > 0.01 or abs(cash) > 0.01:
        only_pm_list.append(p)

only_pm_list.sort(key=lambda x: abs(float(x.get('realizedPnl', 0))), reverse=True)
print(f"Count: {len(only_pm)}, total realizedPnl: ${only_pm_rpnl:.2f}, total cashPnl: ${only_pm_cash:.2f}")
for p in only_pm_list[:20]:
    print(f"  asset={p['asset'][:16]}... out={p.get('outcome',''):3s} rpnl={float(p.get('realizedPnl',0)):+9.2f} cash={float(p.get('cashPnl',0)):+9.2f} bought={float(p.get('totalBought',0)):.1f} | {p.get('title','')[:50]}")

# 6. Summary
print(f"\n{'='*60}")
print(f"SUMMARY")
print(f"{'='*60}")
print(f"Our total realized PnL:           ${result['total_realized_pnl']:>12.2f}")
print(f"  - from common positions:        ${sum_our_rpnl_common:>12.2f}")
print(f"  - from only-ours positions:     ${only_ours_pnl:>12.2f}")
print(f"PM sum realizedPnl (all):         ${pm_sum_realized:>12.2f}")
print(f"  - from common positions:        ${sum_pm_rpnl_common:>12.2f}")
print(f"  - from only-PM positions:       ${only_pm_rpnl:>12.2f}")
print(f"PM sum cashPnl (all):             ${pm_sum_cash:>12.2f}")
print(f"PM cashPnl+realizedPnl:           ${pm_sum_cash+pm_sum_realized:>12.2f}")
gap = result['total_realized_pnl'] - pm_sum_realized
print(f"\nGap (ours - PM realized):         ${gap:>12.2f}")
print(f"Gap from common positions:        ${sum_our_rpnl_common - sum_pm_rpnl_common:>12.2f}")
print(f"Gap from only-ours positions:     ${only_ours_pnl:>12.2f}")

# Check: do split-placeholder positions appear?
split_positions = [a for a in our_by_asset if '_split_' in a]
if split_positions:
    split_pnl = sum(our_by_asset[a]['realized_pnl'] for a in split_positions)
    print(f"\nSplit-placeholder positions: {len(split_positions)}, total PnL: ${split_pnl:.2f}")

# Write findings
findings = []
findings.append("# Position Comparison: Our Calculator vs Polymarket API\n")
findings.append(f"## Counts")
findings.append(f"- Polymarket positions: {len(pm_positions)}")
findings.append(f"- Our positions: {len(our_positions)}")
findings.append(f"- Common: {len(common_assets)}")
findings.append(f"- Only ours: {len(only_ours)}")
findings.append(f"- Only PM: {len(only_pm)}\n")

findings.append(f"## Totals")
findings.append(f"- Our realized PnL: ${result['total_realized_pnl']:.2f}")
findings.append(f"- PM sum(realizedPnl): ${pm_sum_realized:.2f}")
findings.append(f"- PM sum(cashPnl): ${pm_sum_cash:.2f}")
findings.append(f"- PM cashPnl + realizedPnl: ${pm_sum_cash + pm_sum_realized:.2f}")
findings.append(f"- Gap (ours - PM realized): ${gap:.2f}\n")

findings.append(f"## Gap Breakdown")
findings.append(f"- Gap from common positions: ${sum_our_rpnl_common - sum_pm_rpnl_common:.2f}")
findings.append(f"- Gap from only-ours positions: ${only_ours_pnl:.2f}")
findings.append(f"  (positions in our calc but NOT returned by PM API)\n")

findings.append(f"## Top Differences (common positions)")
for d in diffs[:15]:
    if abs(d['rpnl_diff']) < 1:
        break
    findings.append(f"- {d['outcome']} | diff=${d['rpnl_diff']:+.2f} | ours={d['our_rpnl']:+.2f} pm={d['pm_rpnl']:+.2f} | {d['title']}")

findings.append(f"\n## Only-Ours Positions (top by PnL)")
for p in only_ours_list[:15]:
    findings.append(f"- rpnl={p['realized_pnl']:+.2f} | mkt={p.get('market_id','?')} | {p['outcome']} | qty={p['quantity']:.1f}")

findings.append(f"\n## Key Findings")
findings.append(f"_(populated after analysis)_")

with open('POSITION_COMPARISON.md', 'w') as f:
    f.write('\n'.join(findings))

print(f"\nWrote POSITION_COMPARISON.md")
