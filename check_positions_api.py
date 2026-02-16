"""Check Polymarket positions API and profile API for linked wallets."""
import requests
import json

ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
session = requests.Session()
session.headers.update({"Accept": "application/json", "User-Agent": "Mozilla/5.0"})

# 1. Check profile API for linked wallets
print("=== PROFILE API ===")
for endpoint in [
    f"https://data-api.polymarket.com/profile?address={ADDRESS}",
    f"https://data-api.polymarket.com/user?address={ADDRESS}",
    f"https://gamma-api.polymarket.com/users/{ADDRESS}",
]:
    try:
        resp = session.get(endpoint, timeout=10)
        print(f"\n{endpoint}")
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(json.dumps(data, indent=2)[:1500])
    except Exception as ex:
        print(f"Error: {ex}")

# 2. Check positions API  
print("\n\n=== POSITIONS API ===")
all_positions = []
offset = 0
while True:
    resp = session.get(
        "https://data-api.polymarket.com/positions",
        params={"user": ADDRESS, "limit": 500, "offset": offset, "sizeThreshold": 0},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Error: {resp.status_code}")
        break
    data = resp.json()
    if not data:
        break
    all_positions.extend(data)
    if len(data) < 500:
        break
    offset += 500

print(f"Got {len(all_positions)} positions")
if all_positions:
    print(f"Keys: {list(all_positions[0].keys())}")
    
    # Sum PnL fields
    pnl_fields = ['cashPnl', 'realizedPnl', 'currentValue', 'initialValue', 'percentPnl']
    for f in pnl_fields:
        if f in all_positions[0]:
            total = sum(float(p.get(f) or 0) for p in all_positions)
            print(f"  Sum {f}: {total:.2f}")
    
    # Open positions
    open_pos = [p for p in all_positions if float(p.get('size', 0) or 0) > 0]
    print(f"\nOpen positions: {len(open_pos)}")
    open_value = sum(float(p.get('currentValue', 0) or 0) for p in open_pos)
    open_initial = sum(float(p.get('initialValue', 0) or 0) for p in open_pos)
    open_cash_pnl = sum(float(p.get('cashPnl', 0) or 0) for p in open_pos)
    print(f"  Open currentValue: {open_value:.2f}")
    print(f"  Open initialValue: {open_initial:.2f}")
    print(f"  Open cashPnl: {open_cash_pnl:.2f}")
    
    # Closed positions
    closed = [p for p in all_positions if float(p.get('size', 0) or 0) == 0]
    print(f"\nClosed positions: {len(closed)}")
    closed_cash = sum(float(p.get('cashPnl', 0) or 0) for p in closed)
    print(f"  Closed cashPnl: {closed_cash:.2f}")
    
    # Show a sample
    print(f"\nSample position:")
    print(json.dumps(all_positions[0], indent=2)[:800])
