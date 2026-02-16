"""Debug: simulate exactly what _refresh_wallet_data does for wallet 8."""
import os, sys, traceback
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))

import django
django.setup()

from datetime import datetime, timedelta
from wallet_analysis.models import Wallet
from src.api.polymarket_client import PolymarketClient
from src.services.trade_service import TradeService
from wallet_analysis.services import DatabaseService

wallet = Wallet.objects.get(id=8)
address = wallet.address
print(f"Wallet: {wallet.name} / {address}")
print(f"Current DB: trades={wallet.trades.count()}, activities={wallet.activities.count()}")
print(f"data_start={wallet.data_start_date}, data_end={wallet.data_end_date}")

# Use wide date range
start_date = datetime(2024, 1, 1)
end_date = datetime(2026, 2, 16)
after_timestamp = int(start_date.timestamp())
before_timestamp = int(end_date.timestamp())
print(f"\nFetching: {start_date.date()} -> {end_date.date()}")
print(f"Timestamps: {after_timestamp} -> {before_timestamp}")

try:
    client = PolymarketClient()
    trade_service = TradeService(client)
    
    print("\n--- Step 1: Fetching activity ---")
    activity_result = trade_service.get_all_activity(address, after_timestamp, before_timestamp)
    
    trades = activity_result.get("trades", [])
    raw_activity = activity_result.get("raw_activity", {})
    cash_flow = activity_result.get("cash_flow", {})
    errors = raw_activity.get("_errors", {})
    
    print(f"Trades fetched: {len(trades)}")
    for atype, items in raw_activity.items():
        if atype != "_errors" and isinstance(items, list):
            print(f"  Activity {atype}: {len(items)}")
    if errors:
        print(f"  ERRORS: {errors}")
    
    if not trades and not any(isinstance(v, list) and v for k, v in raw_activity.items() if k != "_errors"):
        print("\n*** NO DATA RETURNED FROM API! ***")
        # Try raw API call directly
        print("\n--- Direct API test ---")
        import requests
        r = requests.get(f"https://data-api.polymarket.com/activity?user={address}&limit=5", timeout=10)
        print(f"Direct activity call: status={r.status_code}, items={len(r.json()) if r.status_code==200 else r.text[:200]}")
    else:
        print("\n--- Step 2: Saving to DB ---")
        db_service = DatabaseService()
        if trades:
            saved = db_service.save_trades(wallet, trades)
            print(f"Trades saved: {saved}")
        if raw_activity:
            saved = db_service.save_activities(wallet, raw_activity)
            print(f"Activities saved: {saved}")
        
        print(f"\nAfter save: trades={wallet.trades.count()}, activities={wallet.activities.count()}")

except Exception as e:
    print(f"\n!!! EXCEPTION !!!")
    traceback.print_exc()
