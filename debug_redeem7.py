"""Re-run the full PnL calculator to see what it returns now."""
import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from wallet_analysis.models import Wallet
from wallet_analysis.pnl_calculator import calculate_wallet_pnl

w = Wallet.objects.get(address__startswith='0xbdcd')
print(f"Old cached PnL: ${w.subgraph_realized_pnl:,.2f}")
print(f"Running calculate_wallet_pnl...")
result = calculate_wallet_pnl(w)
for k, v in result.items():
    if isinstance(v, (int, float)):
        print(f"  {k}: ${v:,.2f}")
    elif isinstance(v, dict):
        print(f"  {k}:")
        for kk, vv in v.items():
            print(f"    {kk}: {vv}")
    elif isinstance(v, list):
        print(f"  {k}: {len(v)} items")
    else:
        print(f"  {k}: {v}")
