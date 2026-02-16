import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity
from wallet_analysis.calculators.position_tracker import PositionTracker
from decimal import Decimal

for w in Wallet.objects.all():
    trades = list(Trade.objects.filter(wallet=w).order_by('timestamp'))
    activities = list(Activity.objects.filter(wallet=w).order_by('timestamp'))
    print(f'=== {w.address[:10]} ===')
    print(f'  Trades: {len(trades)}, Activities: {len(activities)}')
    print(f'  Subgraph PnL: ${w.subgraph_realized_pnl:,.2f}')
    
    tracker = PositionTracker()
    positions, events = tracker.process_events(trades, activities)
    
    realized = sum(p.realized_pnl for p in positions.values())
    print(f'  Cost Basis realized: ${realized:,.2f}')
    print(f'  Gap: ${float(w.subgraph_realized_pnl) - float(realized):,.2f}')
    print(f'  Positions: {len(positions)}, PnL events: {len(events)}')
    
    # Count skipped redeems
    skipped = [e for e in events if 'skipped' in str(e).lower() or getattr(e, 'notes', '') == 'skipped']
    print(f'  Skipped events: {len(skipped)}')
    print()
