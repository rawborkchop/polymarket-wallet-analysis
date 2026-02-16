"""Check if our DB has all the data, and analyze the $889 gap."""
import sqlite3
from datetime import datetime

WALLET_ID = 7
conn = sqlite3.connect('db.sqlite3')

# Date range in our DB
c = conn.cursor()
c.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM wallet_analysis_trade WHERE wallet_id=?", (WALLET_ID,))
t_min, t_max, t_count = c.fetchone()
print(f"Trades: {t_count} rows, {datetime.fromtimestamp(t_min)} to {datetime.fromtimestamp(t_max)}")

c.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM wallet_analysis_activity WHERE wallet_id=?", (WALLET_ID,))
a_min, a_max, a_count = c.fetchone()
print(f"Activities: {a_count} rows, {datetime.fromtimestamp(a_min)} to {datetime.fromtimestamp(a_max)}")

# Check wallet data dates
c.execute("SELECT data_start_date, data_end_date FROM wallet_analysis_wallet WHERE id=?", (WALLET_ID,))
row = c.fetchone()
print(f"Wallet data range: {row[0]} to {row[1]}")

# Now let's see if there are activities AFTER our data end date via the API
import requests
import json
ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
s = requests.Session()
s.headers.update({"Accept": "application/json", "User-Agent": "Mozilla/5.0"})

# Get latest activities from API
resp = s.get(f"https://data-api.polymarket.com/activity?user={ADDRESS}&limit=20&offset=0", timeout=10)
if resp.status_code == 200:
    api_activities = resp.json()
    print(f"\nLatest API activities: {len(api_activities)}")
    for a in api_activities[:5]:
        ts = a['timestamp']
        dt = datetime.fromtimestamp(ts)
        print(f"  {dt} {a['type']} {a.get('usdcSize', 0)} USDC - {a['title'][:50]}")
    
    # Check which are after our DB max timestamp
    after_db = [a for a in api_activities if a['timestamp'] > a_max]
    print(f"\n  Activities after DB max ({datetime.fromtimestamp(a_max)}): {len(after_db)}")
    for a in after_db:
        print(f"    {datetime.fromtimestamp(a['timestamp'])} {a['type']} {a.get('usdcSize', 0)}")

# Get latest trades from API
resp = s.get(f"https://data-api.polymarket.com/trades?user={ADDRESS}&limit=20&offset=0", timeout=10)
print(f"\nTrades API status: {resp.status_code}")
if resp.status_code == 200:
    api_trades = resp.json()
    print(f"Latest API trades: {len(api_trades)}")
    if api_trades:
        after_db_trades = [t for t in api_trades if t.get('timestamp', 0) > t_max]
        print(f"Trades after DB max ({datetime.fromtimestamp(t_max)}): {len(after_db_trades)}")

# Also check: what about the CONVERSION activities? They seem to be splits in disguise
c.execute("""
    SELECT activity_type, COUNT(*), SUM(usdc_size), MIN(datetime), MAX(datetime)
    FROM wallet_analysis_activity WHERE wallet_id=? GROUP BY activity_type
""", (WALLET_ID,))
print("\n=== Activity breakdown ===")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]} items, ${row[2]:.2f}, {row[3]} to {row[4]}")

# The gap is $889.59. Let's see if unredeemed positions could explain it
# Positions that are redeemable (resolved but not yet redeemed)
c.execute("""
    SELECT t.asset, t.outcome, SUM(CASE WHEN t.side='BUY' THEN t.size ELSE 0 END) as bought,
           SUM(CASE WHEN t.side='SELL' THEN t.size ELSE 0 END) as sold,
           m.winning_outcome, m.resolved, m.title
    FROM wallet_analysis_trade t
    JOIN wallet_analysis_market m ON t.market_id = m.id
    WHERE t.wallet_id = ?
    GROUP BY t.asset
    HAVING bought - sold > 0.01
""", (WALLET_ID,))
print("\n=== Open/unredeemed positions ===")
total_unredeemed_value = 0
count = 0
for row in c.fetchall():
    asset, outcome, bought, sold, winning, resolved, title = row
    remaining = bought - sold
    if resolved and winning:
        value = remaining if outcome == winning else 0
        if value > 0:
            total_unredeemed_value += value
            count += 1
            if count <= 10:
                print(f"  {title[:60]}: {remaining:.2f} shares of '{outcome}' (winner='{winning}') = ${value:.2f}")

print(f"\nTotal unredeemed winning value: ${total_unredeemed_value:.2f}")
print(f"This might explain part of the gap")

conn.close()
