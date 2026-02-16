import sqlite3
conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()

# Check wallet 7 trades
c.execute("SELECT COUNT(*) FROM wallet_analysis_trade WHERE wallet_id=7")
print("Trades for 1pixel:", c.fetchone()[0])

c.execute("SELECT side, COUNT(*), SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=7 GROUP BY side")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]} trades, ${r[2]:.2f}")

# Sample trades
c.execute("SELECT * FROM wallet_analysis_trade WHERE wallet_id=7 LIMIT 3")
for r in c.fetchall():
    print(r)

# Activities for 1pixel
c.execute("SELECT activity_type, COUNT(*), SUM(usdc_size) FROM wallet_analysis_activity WHERE wallet_id=7 GROUP BY activity_type")
print("\nActivities for 1pixel:")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]} activities, usdc_size=${r[2]}")

# Sample activities
c.execute("SELECT * FROM wallet_analysis_activity WHERE wallet_id=7 AND activity_type='REDEEM' LIMIT 3")
print("\nSample redeems:")
for r in c.fetchall():
    print(r)

# Date range
c.execute("SELECT MIN(datetime), MAX(datetime) FROM wallet_analysis_trade WHERE wallet_id=7")
print("\nTrade date range:", c.fetchone())

c.execute("SELECT MIN(datetime), MAX(datetime) FROM wallet_analysis_activity WHERE wallet_id=7")
print("Activity date range:", c.fetchone())
