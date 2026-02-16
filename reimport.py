"""Re-import 1pixel wallet data with correct address."""
import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from datetime import datetime, timedelta
from wallet_analysis.models import Wallet, Trade, Activity
from wallet_analysis.services import DatabaseService
from src.api.polymarket_client import PolymarketClient
from src.services.trade_service import TradeService
from src.services.analytics_service import AnalyticsService
from wallet_analysis.pnl_calculator import calculate_wallet_pnl

address = '0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c'
w = Wallet.objects.get(address=address)

# Clear old data
old_trades = Trade.objects.filter(wallet=w).count()
old_activities = Activity.objects.filter(wallet=w).count()
print(f"Clearing {old_trades} trades, {old_activities} activities...")
Trade.objects.filter(wallet=w).delete()
Activity.objects.filter(wallet=w).delete()

# Fetch all data since Feb 2025
after_ts = int(datetime(2025, 1, 1).timestamp())
before_ts = int(datetime.now().timestamp())
print(f"Fetching from {datetime.fromtimestamp(after_ts)} to {datetime.fromtimestamp(before_ts)}...")

client = PolymarketClient()
trade_service = TradeService(client)
db_service = DatabaseService()

activity_result = trade_service.get_all_activity(address, after_ts, before_ts)
trades = activity_result.get("trades", [])
raw_activity = activity_result.get("raw_activity", {})

print(f"Fetched {len(trades)} trades")
non_trade = sum(len(items) for k, items in raw_activity.items() if k not in ("TRADE", "_errors") and isinstance(items, list))
print(f"Fetched {non_trade} non-trade activities")

# Save
if trades:
    db_service.save_trades(w, trades)
    print(f"Saved trades. DB count: {Trade.objects.filter(wallet=w).count()}")
if raw_activity:
    db_service.save_activities(w, raw_activity)
    print(f"Saved activities. DB count: {Activity.objects.filter(wallet=w).count()}")

# Calculate PnL
print("Calculating PnL...")
pnl_result = calculate_wallet_pnl(w)
w.subgraph_realized_pnl = pnl_result['total_realized_pnl']
w.save(update_fields=['subgraph_realized_pnl'])

print(f"\n=== Results ===")
print(f"Cost Basis Realized PnL: ${pnl_result['total_realized_pnl']:,.2f}")
print(f"Cash Flow PnL: ${pnl_result['cash_flow_pnl']:,.2f}")
print(f"Polymarket official: $20,172.75")
print(f"Gap: ${20172.75 - pnl_result['total_realized_pnl']:,.2f}")
