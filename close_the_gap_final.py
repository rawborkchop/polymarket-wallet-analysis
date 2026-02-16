"""Close the gap: use Polymarket's /positions endpoint to get their PnL breakdown."""
import requests
import sqlite3
import json

ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
OFFICIAL_PNL = 20172.77
WALLET_ID = 7

session = requests.Session()
session.headers.update({"Accept": "application/json", "User-Agent": "PolymarketWalletAnalyzer/1.0"})

# Fetch all positions from Polymarket API
print("Fetching positions from Polymarket API...")
all_positions = []
offset = 0
while True:
    resp = session.get(
        "https://data-api.polymarket.com/positions",
        params={"user": ADDRESS, "limit": 500, "offset": offset},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  Error: {resp.status_code}")
        break
    data = resp.json()
    if not data:
        break
    all_positions.extend(data)
    if len(data) < 500:
        break
    offset += 500

print(f"Fetched {len(all_positions)} positions")

if all_positions:
    # Show first position to understand the schema
    print(f"\nSample position keys: {list(all_positions[0].keys())}")
    print(f"Sample: {json.dumps(all_positions[0], indent=2)[:600]}")

    # Sum up PnL-related fields
    totals = {}
    numeric_keys = []
    for k, v in all_positions[0].items():
        if isinstance(v, (int, float)):
            numeric_keys.append(k)
    
    for k in numeric_keys:
        totals[k] = sum(p.get(k, 0) or 0 for p in all_positions)
    
    print(f"\n{'Field':<30s} {'Total':>15s}")
    print("-" * 47)
    for k, v in sorted(totals.items()):
        print(f"  {k:<28s} {v:>15.2f}")

    # String fields that might be interesting
    for k, v in all_positions[0].items():
        if isinstance(v, str) and k not in ('proxyWallet', 'conditionId', 'asset', 'slug', 'icon', 'title', 'groupSlug', 'endDate', 'curatedOrder'):
            vals = set(p.get(k, '') for p in all_positions)
            if len(vals) < 10:
                print(f"  {k} values: {vals}")

# Now compare with our DB
print("\n\n=== COMPARISON WITH OUR DB ===")
conn = sqlite3.connect("db.sqlite3")
c = conn.cursor()

# Our V2 cash flow
c.execute("SELECT side, SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=? GROUP BY side", (WALLET_ID,))
trade_sums = dict(c.fetchall())

c.execute("SELECT activity_type, SUM(usdc_size) FROM wallet_analysis_activity WHERE wallet_id=? GROUP BY activity_type", (WALLET_ID,))
act_sums = dict(c.fetchall())

buy_cost = trade_sums.get("BUY", 0)
sell_rev = trade_sums.get("SELL", 0)
redeem = act_sums.get("REDEEM", 0)
merge = act_sums.get("MERGE", 0)
split = act_sums.get("SPLIT", 0)
reward = act_sums.get("REWARD", 0)
conversion = act_sums.get("CONVERSION", 0)

v2 = sell_rev + redeem + merge - buy_cost - split
print(f"V2 cash flow: {v2:.2f}")
print(f"V2 + rewards: {v2 + reward:.2f}")
print(f"Gap from official: {OFFICIAL_PNL - v2 - reward:.2f}")

# If we have cashPnl from positions, that's Polymarket's calculation
if all_positions and 'cashPnl' in all_positions[0]:
    total_cash_pnl = sum(p.get('cashPnl', 0) or 0 for p in all_positions)
    print(f"\nPolymarket cashPnl sum: {total_cash_pnl:.2f}")
    
if all_positions and 'currentValue' in all_positions[0]:
    total_current = sum(p.get('currentValue', 0) or 0 for p in all_positions)
    total_initial = sum(p.get('initialValue', 0) or 0 for p in all_positions)
    print(f"Polymarket currentValue sum: {total_current:.2f}")
    print(f"Polymarket initialValue sum: {total_initial:.2f}")
    print(f"currentValue - initialValue: {total_current - total_initial:.2f}")

conn.close()
