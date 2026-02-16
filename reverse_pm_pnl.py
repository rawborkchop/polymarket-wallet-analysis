"""Reverse-engineer Polymarket PnL calculation for wallet 1pixel."""
import urllib.request
import json
from datetime import datetime, timedelta, timezone

ADDR = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def fetch_all_positions():
    """Fetch all positions, paginating via offset."""
    all_pos = []
    offset = 0
    limit = 100
    while True:
        url = f"https://data-api.polymarket.com/positions?user={ADDR}&sizeThreshold=0&limit={limit}&offset={offset}"
        data = fetch(url)
        if not data:
            break
        all_pos.extend(data)
        if len(data) < limit:
            break
        offset += limit
        print(f"  fetched {len(all_pos)} positions so far...")
    return all_pos

print("=== FETCHING POSITIONS ===")
positions = fetch_all_positions()
print(f"Total positions: {len(positions)}")

# Show first position structure
if positions:
    print("\nSample position keys:", list(positions[0].keys()))
    print("Sample position:", json.dumps(positions[0], indent=2)[:1500])

# Categorize
active = [p for p in positions if float(p.get("size", 0)) > 0]
closed = [p for p in positions if float(p.get("size", 0)) == 0]
print(f"\nActive positions: {len(active)}, Closed positions: {len(closed)}")

# Sum PnL fields
pnl_fields = ["realizedPnl", "cashPnl", "curPnl", "percentPnl", "totalPnl", "initialValue", "currentValue"]
print("\n=== PNL FIELD SUMS (ALL POSITIONS) ===")
for field in pnl_fields:
    vals = [float(p.get(field, 0)) for p in positions if p.get(field) is not None]
    if vals:
        print(f"  {field}: sum={sum(vals):.4f}, count={len(vals)}")

print("\n=== PNL FIELD SUMS (ACTIVE ONLY) ===")
for field in pnl_fields:
    vals = [float(p.get(field, 0)) for p in active if p.get(field) is not None]
    if vals:
        print(f"  {field}: sum={sum(vals):.4f}, count={len(vals)}")

print("\n=== PNL FIELD SUMS (CLOSED ONLY) ===")
for field in pnl_fields:
    vals = [float(p.get(field, 0)) for p in closed if p.get(field) is not None]
    if vals:
        print(f"  {field}: sum={sum(vals):.4f}, count={len(vals)}")

# Time-based analysis: 1 month
one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
print(f"\n=== TIME-BASED ANALYSIS (since {one_month_ago.strftime('%Y-%m-%d')}) ===")

# Check what time fields exist
time_fields = [k for k in positions[0].keys() if 'time' in k.lower() or 'date' in k.lower() or 'created' in k.lower() or 'updated' in k.lower()]
print(f"Time-related fields: {time_fields}")

# Try to filter by time
for tf in time_fields:
    sample = positions[0].get(tf)
    print(f"  {tf} sample: {sample}")

# Check if there's a startDate/endDate param for positions
print("\n=== TRYING POSITIONS WITH startDate PARAM ===")
start_str = one_month_ago.strftime("%Y-%m-%dT%H:%M:%SZ")
try:
    url = f"https://data-api.polymarket.com/positions?user={ADDR}&sizeThreshold=0&startDate={start_str}"
    timed = fetch(url)
    print(f"Positions with startDate: {len(timed)}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== FETCHING TRADES ===")
trades_url = f"https://data-api.polymarket.com/trades?user={ADDR}&limit=100"
try:
    trades = fetch(trades_url)
    print(f"Trades count: {len(trades)}")
    if trades:
        print("Trade keys:", list(trades[0].keys()))
        print("Sample trade:", json.dumps(trades[0], indent=2)[:1000])
except Exception as e:
    print(f"Trades error: {e}")
    trades = []

print("\n=== FETCHING ACTIVITY ===")
activity_url = f"https://data-api.polymarket.com/activity?user={ADDR}&limit=100"
try:
    activity = fetch(activity_url)
    print(f"Activity count: {len(activity)}")
    if activity:
        print("Activity keys:", list(activity[0].keys()))
        print("Sample activity:", json.dumps(activity[0], indent=2)[:1000])
except Exception as e:
    print(f"Activity error: {e}")
    activity = []

# Try the profit endpoint directly
print("\n=== TRYING PROFIT/PNL ENDPOINTS ===")
for endpoint in [
    f"https://data-api.polymarket.com/pnl?user={ADDR}",
    f"https://data-api.polymarket.com/profit?user={ADDR}",
    f"https://data-api.polymarket.com/earnings?user={ADDR}",
    f"https://data-api.polymarket.com/portfolio?user={ADDR}",
    f"https://data-api.polymarket.com/pnl/timeseries?user={ADDR}",
    f"https://data-api.polymarket.com/profits?user={ADDR}&window=1m",
    f"https://data-api.polymarket.com/profits?user={ADDR}",
    f"https://profit-api.polymarket.com/profits?user={ADDR}",
    f"https://data-api.polymarket.com/rank?user={ADDR}",
]:
    try:
        data = fetch(endpoint)
        print(f"\n{endpoint}")
        print(f"  Response: {json.dumps(data, indent=2)[:500]}")
    except urllib.error.HTTPError as e:
        print(f"\n{endpoint} → {e.code}")
    except Exception as e:
        print(f"\n{endpoint} → {e}")

# Try to compute 1M PnL from positions with timestamps
print("\n=== COMPUTING 1M PnL FROM POSITIONS ===")
recent_positions = []
for p in positions:
    # Try various timestamp fields
    for tf in ['createdAt', 'updatedAt', 'timestamp', 'endDate']:
        ts = p.get(tf)
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                else:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                if dt >= one_month_ago:
                    recent_positions.append(p)
                break
            except:
                pass

print(f"Positions with recent activity: {len(recent_positions)}")
if recent_positions:
    for field in ["realizedPnl", "cashPnl", "curPnl", "totalPnl"]:
        vals = [float(p.get(field, 0)) for p in recent_positions if p.get(field) is not None]
        if vals:
            print(f"  Recent {field}: sum={sum(vals):.4f}")

# Dump all unique field values for analysis
print("\n=== ALL POSITION FIELDS WITH SAMPLE VALUES ===")
if positions:
    for k, v in positions[0].items():
        print(f"  {k}: {repr(v)[:100]}")

print("\n=== TARGET VALUES ===")
print(f"Looking for: 1M=$1,282.17  ALL=$20,172.75")
total_realized = sum(float(p.get("realizedPnl", 0)) for p in positions)
total_cash = sum(float(p.get("cashPnl", 0)) for p in positions)
total_cur = sum(float(p.get("curPnl", 0)) for p in positions)
print(f"Total realizedPnl: ${total_realized:.2f}")
print(f"Total cashPnl: ${total_cash:.2f}")
print(f"Total curPnl: ${total_cur:.2f}")
print(f"realized+cur: ${total_realized+total_cur:.2f}")
print(f"cash+cur: ${total_cash+total_cur:.2f}")
