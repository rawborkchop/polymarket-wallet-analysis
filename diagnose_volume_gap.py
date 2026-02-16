"""
Diagnostic script to investigate the $569K volume gap for wallet 1pixel.

Our DB: $204,117 volume
Polymarket profile: $773,199.66
Gap: ~$569K

Hypothesis: Polymarket "volume" = sum of `size` (shares traded),
while our DB `total_volume_usd` = sum of `size * price` (notional value).
"""

import os
import sys
import django
import requests
from decimal import Decimal

# Setup Django
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity

WALLET_ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
WALLET_DB_ID = 7
POLYMARKET_VOLUME = Decimal("773199.66")

def query_db():
    """Check what we have in our DB."""
    print("=" * 60)
    print("DATABASE ANALYSIS")
    print("=" * 60)

    wallet = Wallet.objects.get(id=WALLET_DB_ID)
    trades = Trade.objects.filter(wallet=wallet)
    
    count = trades.count()
    print(f"Trade count in DB: {count}")
    
    # Our current volume calculation: sum(size * price) = sum(total_value)
    notional_volume = sum(t.total_value for t in trades.iterator())
    print(f"Notional volume (sum of size*price): ${notional_volume:,.2f}")
    
    # Alternative: sum of size (share count)
    share_volume = sum(t.size for t in trades.iterator())
    print(f"Share volume (sum of size): ${share_volume:,.2f}")
    
    # Buy-only volumes
    buys = trades.filter(side='BUY')
    sells = trades.filter(side='SELL')
    
    buy_notional = sum(t.total_value for t in buys.iterator())
    buy_shares = sum(t.size for t in buys.iterator())
    sell_notional = sum(t.total_value for t in sells.iterator())
    sell_shares = sum(t.size for t in sells.iterator())
    
    print(f"\nBUY trades: {buys.count()}")
    print(f"  Notional (size*price): ${buy_notional:,.2f}")
    print(f"  Shares (size): ${buy_shares:,.2f}")
    print(f"\nSELL trades: {sells.count()}")
    print(f"  Notional (size*price): ${sell_notional:,.2f}")
    print(f"  Shares (size): ${sell_shares:,.2f}")
    
    print(f"\nPolymarket displayed volume: ${POLYMARKET_VOLUME:,.2f}")
    print(f"Gap if notional:  ${POLYMARKET_VOLUME - notional_volume:,.2f}")
    print(f"Gap if shares:    ${POLYMARKET_VOLUME - share_volume:,.2f}")
    
    # Check activities too - splits/merges create volume?
    activities = Activity.objects.filter(wallet=wallet)
    for atype in ['REDEEM', 'SPLIT', 'MERGE', 'REWARD', 'CONVERSION']:
        acts = activities.filter(activity_type=atype)
        if acts.exists():
            total_usdc = sum(a.usdc_size for a in acts.iterator())
            total_size = sum(a.size for a in acts.iterator())
            print(f"\n{atype}: {acts.count()} activities, usdc_size=${total_usdc:,.2f}, size={total_size:,.2f}")
    
    return {
        'count': count,
        'notional': notional_volume,
        'shares': share_volume,
        'buy_shares': buy_shares,
        'sell_shares': sell_shares,
    }


def query_api_count():
    """Check total trade count from the API."""
    print("\n" + "=" * 60)
    print("API ANALYSIS")
    print("=" * 60)
    
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "User-Agent": "DiagnosticScript/1.0"})
    
    # Fetch first batch to check structure
    params = {
        "user": WALLET_ADDRESS,
        "limit": 1,
        "sortBy": "TIMESTAMP",
        "sortDirection": "DESC",
    }
    resp = session.get("https://data-api.polymarket.com/activity", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    
    if data:
        print(f"Sample activity item keys: {list(data[0].keys())}")
        print(f"Sample item type: {data[0].get('type')}")
        if data[0].get('type') == 'TRADE':
            print(f"  size: {data[0].get('size')}")
            print(f"  price: {data[0].get('price')}")
            print(f"  usdcSize: {data[0].get('usdcSize')}")
            print(f"  side: {data[0].get('side')}")
    
    # Count all activity via pagination
    print("\nCounting all activities from API...")
    all_items = []
    current_end = None
    
    for i in range(500):
        params = {
            "user": WALLET_ADDRESS,
            "limit": 500,
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC",
        }
        if current_end:
            params["end"] = current_end
        
        resp = session.get("https://data-api.polymarket.com/activity", params=params, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        
        if not batch:
            break
        
        all_items.extend(batch)
        print(f"  Fetched {len(all_items)} items...", end="\r")
        
        if len(batch) < 500:
            break
        
        min_ts = min(item.get("timestamp", 0) for item in batch)
        current_end = min_ts - 1
    
    print(f"\nTotal activities from API: {len(all_items)}")
    
    # Break down by type
    by_type = {}
    for item in all_items:
        t = item.get('type', 'UNKNOWN')
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(item)
    
    for t, items in sorted(by_type.items()):
        print(f"  {t}: {len(items)}")
    
    # Calculate volume different ways for TRADE items
    trades = by_type.get('TRADE', [])
    if trades:
        api_notional = sum(Decimal(str(t.get('size', 0))) * Decimal(str(t.get('price', 0))) for t in trades)
        api_shares = sum(Decimal(str(t.get('size', 0))) for t in trades)
        api_usdc = sum(Decimal(str(t.get('usdcSize', 0))) for t in trades if t.get('usdcSize'))
        
        print(f"\nAPI TRADE volume calculations:")
        print(f"  Notional (size*price): ${api_notional:,.2f}")
        print(f"  Shares (sum of size): ${api_shares:,.2f}")
        print(f"  usdcSize (if present): ${api_usdc:,.2f}")
        print(f"\n  Polymarket displayed:  ${POLYMARKET_VOLUME:,.2f}")
        print(f"  Match notional? Gap:   ${POLYMARKET_VOLUME - api_notional:,.2f}")
        print(f"  Match shares? Gap:     ${POLYMARKET_VOLUME - api_shares:,.2f}")
        print(f"  Match usdcSize? Gap:   ${POLYMARKET_VOLUME - api_usdc:,.2f}")
        
        # Also check if activities (splits, merges etc) contribute
        all_usdc = sum(Decimal(str(item.get('usdcSize', 0))) for item in all_items if item.get('usdcSize'))
        all_size = sum(Decimal(str(item.get('size', 0))) for item in all_items)
        print(f"\n  ALL activities usdcSize: ${all_usdc:,.2f}")
        print(f"  ALL activities size:     ${all_size:,.2f}")
    
    return {
        'api_total': len(all_items),
        'api_trades': len(trades),
        'by_type': {t: len(items) for t, items in by_type.items()},
    }


def check_date_gaps(db_data):
    """Check for date ranges with missing trades."""
    print("\n" + "=" * 60)
    print("DATE RANGE ANALYSIS")
    print("=" * 60)
    
    wallet = Wallet.objects.get(id=WALLET_DB_ID)
    trades = Trade.objects.filter(wallet=wallet).order_by('timestamp')
    
    if not trades.exists():
        print("No trades found")
        return
    
    first = trades.first()
    last = trades.last()
    
    from datetime import datetime
    print(f"First trade: {datetime.fromtimestamp(first.timestamp)} (ts={first.timestamp})")
    print(f"Last trade:  {datetime.fromtimestamp(last.timestamp)} (ts={last.timestamp})")
    print(f"Wallet data_start_date: {wallet.data_start_date}")
    print(f"Wallet data_end_date: {wallet.data_end_date}")
    
    # Check monthly distribution
    from collections import defaultdict
    monthly = defaultdict(lambda: {'count': 0, 'notional': Decimal('0'), 'shares': Decimal('0')})
    for t in trades.iterator():
        month = datetime.fromtimestamp(t.timestamp).strftime('%Y-%m')
        monthly[month]['count'] += 1
        monthly[month]['notional'] += t.total_value
        monthly[month]['shares'] += t.size
    
    print(f"\nMonthly breakdown:")
    print(f"{'Month':<10} {'Count':>7} {'Notional':>14} {'Shares':>14}")
    for month in sorted(monthly.keys()):
        d = monthly[month]
        print(f"{month:<10} {d['count']:>7} ${d['notional']:>12,.2f} ${d['shares']:>12,.2f}")


if __name__ == '__main__':
    db_data = query_db()
    api_data = query_api_count()
    check_date_gaps(db_data)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"DB trade count:  {db_data['count']}")
    print(f"API trade count: {api_data['api_trades']}")
    print(f"Count gap:       {api_data['api_trades'] - db_data['count']}")
    print(f"\nDB notional volume:  ${db_data['notional']:,.2f}")
    print(f"DB share volume:     ${db_data['shares']:,.2f}")
    print(f"Polymarket volume:   ${POLYMARKET_VOLUME:,.2f}")
    print(f"\nConclusion:")
    
    share_gap = abs(POLYMARKET_VOLUME - db_data['shares'])
    notional_gap = abs(POLYMARKET_VOLUME - db_data['notional'])
    
    if share_gap < notional_gap:
        print(f"  Share volume is CLOSER to Polymarket ({share_gap:,.2f} gap vs {notional_gap:,.2f})")
        print(f"  => Polymarket 'volume' likely = sum of shares (size), NOT notional (size*price)")
    else:
        print(f"  Notional is CLOSER to Polymarket ({notional_gap:,.2f} gap vs {share_gap:,.2f})")
