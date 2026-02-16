"""Try Polymarket APIs and explore net-position-based PnL."""
import sqlite3
import requests
import json

conn = sqlite3.connect("db.sqlite3")
c = conn.cursor()
WALLET_ID = 7
ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
OFFICIAL_PNL = 20172.77

# Try various Polymarket API endpoints
endpoints = [
    f"https://data-api.polymarket.com/value/{ADDRESS}",
    f"https://data-api.polymarket.com/pnl/{ADDRESS}",
    f"https://data-api.polymarket.com/profit/{ADDRESS}",
    f"https://lb-api.polymarket.com/leaderboard?window=all&limit=1&name=1pixel",
    f"https://lb-api.polymarket.com/leaders?window=all&limit=1&name=1pixel",
    f"https://clob.polymarket.com/rewards?address={ADDRESS}",
]

headers = {"User-Agent": "Mozilla/5.0"}

for url in endpoints:
    try:
        resp = requests.get(url, timeout=10, headers=headers)
        print(f"\n{url}")
        print(f"  Status: {resp.status_code}")
        if resp.ok:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                print(f"  {json.dumps(data[0] if len(data) < 5 else data[:2], indent=2)[:500]}")
            elif isinstance(data, dict):
                print(f"  {json.dumps(data, indent=2)[:500]}")
    except Exception as e:
        print(f"  Error: {e}")

# Now let's try the position-based PnL calculation
print("\n\n=== POSITION-BASED PnL ===")

# Get all markets for this wallet
c.execute("""
    SELECT DISTINCT t.market_id, m.title
    FROM wallet_analysis_trade t
    JOIN wallet_analysis_market m ON t.market_id = m.id
    WHERE t.wallet_id=?
""", (WALLET_ID,))
markets = c.fetchall()
print(f"Total markets traded: {len(markets)}")

total_pnl = 0
total_realized = 0

for market_id, title in markets:
    # Trades
    c.execute("""
        SELECT side, SUM(size), SUM(total_value)
        FROM wallet_analysis_trade 
        WHERE wallet_id=? AND market_id=?
        GROUP BY side
    """, (WALLET_ID, market_id))
    
    buy_size = buy_cost = sell_size = sell_rev = 0
    for r in c.fetchall():
        if r[0] == 'BUY':
            buy_size, buy_cost = r[1], r[2]
        elif r[0] == 'SELL':
            sell_size, sell_rev = r[1], r[2]
    
    # Activities for this market
    c.execute("""
        SELECT activity_type, SUM(size), SUM(usdc_size)
        FROM wallet_analysis_activity
        WHERE wallet_id=? AND market_id=?
        GROUP BY activity_type
    """, (WALLET_ID, market_id))
    
    redeem_size = redeem_usdc = 0
    split_size = split_usdc = 0
    merge_size = merge_usdc = 0
    conv_size = conv_usdc = 0
    
    for r in c.fetchall():
        at, sz, usdc = r[0], r[1] or 0, r[2] or 0
        if at == 'REDEEM':
            redeem_size, redeem_usdc = sz, usdc
        elif at == 'SPLIT':
            split_size, split_usdc = sz, usdc
        elif at == 'MERGE':
            merge_size, merge_usdc = sz, usdc
        elif at == 'CONVERSION':
            conv_size, conv_usdc = sz, usdc
    
    # Net position
    net = buy_size - sell_size - redeem_size + split_size - merge_size
    # Note: split adds tokens, merge/conversion removes tokens
    
    # Realized PnL for this market
    realized = sell_rev + redeem_usdc + merge_usdc - buy_cost - split_usdc
    total_realized += realized

print(f"\nTotal realized PnL (per-market): {total_realized:.2f}")

# Now check: where are the rewards allocated?
c.execute("""
    SELECT market_id, SUM(usdc_size)
    FROM wallet_analysis_activity
    WHERE wallet_id=? AND activity_type='REWARD'
    GROUP BY market_id
""", (WALLET_ID,))
reward_total = 0
for r in c.fetchall():
    reward_total += r[1]
print(f"Total rewards: {reward_total:.2f}")
print(f"Realized + rewards: {total_realized + reward_total:.2f}")

# Check volume: is Polymarket's volume = SUM(size) for all trades?
c.execute("SELECT SUM(size) FROM wallet_analysis_trade WHERE wallet_id=?", (WALLET_ID,))
our_vol = c.fetchone()[0]
print(f"\nOur volume (sum of size): {our_vol:.2f}")
print(f"Official volume: 773199.66")
print(f"Missing volume: {773199.66 - our_vol:.2f}")

# Maybe the missing volume = missing trades that have PnL impact
# If missing $1337 in volume, and those were e.g. profitable sells...
# Average profit per share sold = (sell_rev - cost_of_sold_shares) / sell_size

# Actually, what if conversions contribute to volume?
c.execute("""
    SELECT SUM(size) FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='CONVERSION'
""", (WALLET_ID,))
conv_vol = c.fetchone()[0]
print(f"Conversion volume: {conv_vol:.2f}")
print(f"Trade size + conversion: {our_vol + conv_vol:.2f}")

# Maybe volume = trade_size + some activities?
for combo_name, combo_val in [
    ("trades only", our_vol),
    ("trades + conversions", our_vol + conv_vol),
    ("trades + all activities", our_vol + 132769.14),
]:
    print(f"  {combo_name}: {combo_val:.2f} (diff: {773199.66 - combo_val:.2f})")

conn.close()
