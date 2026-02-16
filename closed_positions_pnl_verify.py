"""
Verification: PM monthly PnL ≈ resolved_market_pnl + current_unrealized

Resolved market PnL = for each market with redeems in period:
  sell_revenue + redeem_revenue + merge_revenue - buy_cost - split_cost
  (using ALL-TIME trades for cost basis, not just period)

Current unrealized = sum(currentValue - initialValue) from positions API

Our result: $1,441.23 + (-$691.74) = $749.49 vs target $710.14 (gap $39.35)

The gap is likely from our DB having ~277 extra buys, ~47 extra sells, ~8 extra redeems
vs PM's activity API. Let's investigate the discrepancy.
"""
import sqlite3, json, urllib.request
from collections import defaultdict
from datetime import datetime

WALLET_ID = 7
ADDR = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"

conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row

# Check: are there markets with redeems where usdc_size=0 that we might be missing?
zero_redeems = conn.execute("""
    SELECT COUNT(*), COUNT(DISTINCT market_id) FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='REDEEM' AND usdc_size=0
    AND datetime >= '2026-01-17' AND datetime < '2026-02-16'
""", (WALLET_ID,)).fetchall()
print(f"Zero-value redeems in period: {zero_redeems[0][0]} across {zero_redeems[0][1]} markets")

# Markets with ONLY zero redeems (losing positions)
losing = conn.execute("""
    SELECT a.market_id, SUM(a.usdc_size) as total_redeem, m.title
    FROM wallet_analysis_activity a
    LEFT JOIN wallet_analysis_market m ON a.market_id = m.id
    WHERE a.wallet_id=? AND a.activity_type='REDEEM'
    AND a.datetime >= '2026-01-17' AND a.datetime < '2026-02-16'
    GROUP BY a.market_id
    HAVING total_redeem = 0
""", (WALLET_ID,)).fetchall()

print(f"\nMarkets resolved with $0 redeem (losses): {len(losing)}")
losing_pnl = 0
for l in losing:
    mid = l["market_id"]
    buy_cost = float(conn.execute(
        "SELECT COALESCE(SUM(total_value),0) FROM wallet_analysis_trade WHERE wallet_id=? AND market_id=? AND side='BUY'",
        (WALLET_ID, mid)).fetchone()[0])
    sell_rev = float(conn.execute(
        "SELECT COALESCE(SUM(total_value),0) FROM wallet_analysis_trade WHERE wallet_id=? AND market_id=? AND side='SELL'",
        (WALLET_ID, mid)).fetchone()[0])
    split_cost = float(conn.execute(
        "SELECT COALESCE(SUM(usdc_size),0) FROM wallet_analysis_activity WHERE wallet_id=? AND market_id=? AND activity_type='SPLIT'",
        (WALLET_ID, mid)).fetchone()[0])
    merge_rev = float(conn.execute(
        "SELECT COALESCE(SUM(usdc_size),0) FROM wallet_analysis_activity WHERE wallet_id=? AND market_id=? AND activity_type='MERGE'",
        (WALLET_ID, mid)).fetchone()[0])
    pnl = sell_rev + merge_rev - buy_cost - split_cost
    losing_pnl += pnl
    if abs(pnl) > 50:
        print(f"  Market {mid}: PnL=${pnl:>8.2f} buy=${buy_cost:.2f} sell=${sell_rev:.2f} | {l['title'][:50] if l['title'] else '?'}")

print(f"Losing markets PnL: ${losing_pnl:,.2f}")

# Now: include zero-redeem markets
# Total resolved PnL = winning redeems PnL + losing redeems PnL
winning_pnl = 1441.23  # from previous script
total_resolved = winning_pnl + losing_pnl

# Unrealized
unrealized = -691.74

print(f"\n=== Updated calculation ===")
print(f"Winning resolved PnL: ${winning_pnl:,.2f}")
print(f"Losing resolved PnL: ${losing_pnl:,.2f}")
print(f"Total resolved: ${total_resolved:,.2f}")
print(f"Unrealized: ${unrealized:,.2f}")
print(f"Monthly PnL: ${total_resolved + unrealized:,.2f}")
print(f"Target: $710.14")

# ── Also check: which redeems in our DB are NOT in PM API? ──
# Our DB has 346 redeems vs PM's 338 (8 extra, $4,636 extra)
# Those 8 extra redeems inflate our resolved PnL
# Let's see redeems ordered by size to find the big ones
big_redeems = conn.execute("""
    SELECT a.market_id, a.usdc_size, a.datetime, m.title
    FROM wallet_analysis_activity a
    LEFT JOIN wallet_analysis_market m ON a.market_id = m.id
    WHERE a.wallet_id=? AND a.activity_type='REDEEM'
    AND a.datetime >= '2026-01-17' AND a.datetime < '2026-02-16'
    AND a.usdc_size > 0
    ORDER BY a.usdc_size DESC
    LIMIT 20
""", (WALLET_ID,)).fetchall()

print(f"\nTop 20 redeems in period:")
for r in big_redeems:
    print(f"  ${float(r['usdc_size']):>10.2f}  {r['datetime']}  market={r['market_id']}  {r['title'][:50] if r['title'] else '?'}")

conn.close()
