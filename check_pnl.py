import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity
from wallet_analysis.pnl_calculator import calculate_wallet_pnl

for w in Wallet.objects.all():
    trades = Trade.objects.filter(wallet=w).count()
    activities = Activity.objects.filter(wallet=w).count()
    print(f'=== {w.address} ===')
    print(f'  Trades: {trades}, Activities: {activities}')
    print(f'  Subgraph PnL (cached): ${w.subgraph_realized_pnl:,.2f}')
    try:
        cb = calculate_wallet_pnl(w)
        print(f'  Cost Basis realized: ${cb["total_realized_pnl"]:,.2f}')
        print(f'  Cost Basis unrealized: ${cb["total_unrealized_pnl"]:,.2f}')
        print(f'  Cost Basis total: ${cb["total_pnl"]:,.2f}')
        print(f'  Cash Flow PnL: ${cb["cash_flow_pnl"]:,.2f}')
        print(f'  Positions tracked: {len(cb.get("positions", []))}')
    except Exception as e:
        import traceback
        traceback.print_exc()
    print()
