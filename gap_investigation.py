"""Investigate the ~$869 PnL gap for 1pixel wallet using avg cost basis methodology."""
import sqlite3
import json
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
OFFICIAL_PNL = 20172.77
WALLET_ID = 7

conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 1. Explore schema
print("=== SCHEMA ===")
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print(tables)

for t in tables:
    if 'wallet' in t.lower() or 'trade' in t.lower() or 'activity' in t.lower() or 'position' in t.lower():
        c.execute(f"PRAGMA table_info({t})")
        cols = [(r[1], r[2]) for r in c.fetchall()]
        c.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = c.fetchone()[0]
        print(f"\n{t} ({cnt} rows): {cols}")

# 2. Get all trades for this wallet, ordered by time
print("\n\n=== TRADES ===")
c.execute("SELECT * FROM wallet_analysis_trade WHERE wallet_id=? ORDER BY timestamp ASC LIMIT 3", (WALLET_ID,))
rows = c.fetchall()
if rows:
    print("Columns:", [d[0] for d in c.description])
    for r in rows:
        print(dict(r))

# 3. Get all activities
print("\n\n=== ACTIVITIES ===")
c.execute("SELECT * FROM wallet_analysis_activity WHERE wallet_id=? ORDER BY timestamp ASC LIMIT 3", (WALLET_ID,))
rows = c.fetchall()
if rows:
    print("Columns:", [d[0] for d in c.description])
    for r in rows:
        print(dict(r))

# 4. Counts
c.execute("SELECT side, COUNT(*), SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=? GROUP BY side", (WALLET_ID,))
for r in c.fetchall():
    print(f"Trades {r[0]}: {r[1]} trades, total_value={r[2]:.2f}")

c.execute("SELECT activity_type, COUNT(*), SUM(usdc_size) FROM wallet_analysis_activity WHERE wallet_id=? GROUP BY activity_type", (WALLET_ID,))
for r in c.fetchall():
    print(f"Activity {r[0]}: {r[1]} items, usdc_size={r[2]:.2f}")

conn.close()
