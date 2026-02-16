"""Compare PnL with and without the new Stage 2 inference to isolate its effect."""
import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity
from wallet_analysis.calculators.position_tracker import PositionTracker
from decimal import Decimal

w = Wallet.objects.get(address__startswith='0xbdcd')
trades = list(Trade.objects.filter(wallet=w).order_by('timestamp'))
activities = list(Activity.objects.filter(wallet=w).order_by('timestamp'))

# Run with default (includes Stage 2 inference)
tracker = PositionTracker()
positions, events = tracker.process_events(trades, activities)
realized_new = sum(p.realized_pnl for p in positions.values())

# Check positions created by redeem inference (no prior buys/trades)
ghost_positions = [(a, p) for a, p in positions.items() 
                   if p.total_bought == Decimal('0') and p.total_sold == Decimal('0') and p.realized_pnl != Decimal('0')]

print(f"Total realized PnL (with fix): ${realized_new:,.2f}")
print(f"Ghost positions (no buys, has PnL): {len(ghost_positions)}")
ghost_pnl = sum(p.realized_pnl for _, p in ghost_positions)
print(f"Ghost PnL total: ${ghost_pnl:,.2f}")

for a, p in ghost_positions[:10]:
    print(f"  asset={a[:20]}... qty={p.quantity} avg={p.avg_price} pnl=${p.realized_pnl:.2f} revenue={p.total_revenue}")

# Count positions with negative PnL
neg_pnl = [(a, p) for a, p in positions.items() if p.realized_pnl < 0]
print(f"\nPositions with negative PnL: {len(neg_pnl)}")
print(f"Total negative PnL: ${sum(p.realized_pnl for _, p in neg_pnl):,.2f}")

# Count positions with positive PnL
pos_pnl = [(a, p) for a, p in positions.items() if p.realized_pnl > 0]
print(f"Positions with positive PnL: {len(pos_pnl)}")
print(f"Total positive PnL: ${sum(p.realized_pnl for _, p in pos_pnl):,.2f}")
