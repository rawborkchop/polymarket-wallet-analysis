"""
FINAL: Two competing theories for PM's monthly PnL = $710.14

Theory A: Mark-to-market
  monthly = cashflow_in_period + portfolio_now - portfolio_30d_ago
  Using PM API: $1,886.65 + $20.29 - $1,196.80 = $710.14
  (We need to know portfolio_30d_ago = $1,196.80 to make it work)

Theory B: Realized + Unrealized
  monthly = resolved_market_pnl + current_unrealized
  = $1,393.34 + (-$691.74) = $701.60 (close but not exact)
  
Let's refine Theory B and check if using PM API data (not our DB) gets closer.
"""
import sqlite3, json, urllib.request, time
from collections import defaultdict
from datetime import datetime

WALLET_ID = 7
ADDR = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
PERIOD_START = datetime(2026, 1, 16)
PERIOD_END = datetime(2026, 2, 16)

conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row

# Get current positions
url = f"https://data-api.polymarket.com/positions?user={ADDR}&sizeThreshold=0"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=10) as r:
    positions = json.loads(r.read())

unrealized = sum(float(p.get("currentValue", 0)) - float(p.get("initialValue", 0)) for p in positions)
realized_current = sum(float(p.get("realizedPnl", 0)) for p in positions)
portfolio_value = sum(float(p.get("currentValue", 0)) for p in positions)

print(f"Current positions: {len(positions)}")
print(f"Portfolio value: ${portfolio_value:,.2f}")
print(f"Unrealized PnL: ${unrealized:,.2f}")
print(f"Realized from current positions: ${realized_current:,.2f}")

# ── Compute resolved-market PnL more carefully ──
# Using only PM API-consistent data (matching date range of PM API)
# PM API goes from timestamp 1768650762 (Jan 17) to 1771178015 (Feb 15)
# Let's use the same range

pm_start = datetime(2026, 1, 17)
pm_end = datetime(2026, 2, 16)

# Markets that had redeems in the period
redeems_in_period = conn.execute("""
    SELECT market_id, SUM(usdc_size) as total_redeem
    FROM wallet_analysis_activity WHERE wallet_id=? AND activity_type='REDEEM' 
    AND datetime >= '2026-01-17' AND datetime < '2026-02-16'
    AND usdc_size > 0
    GROUP BY market_id
""", (WALLET_ID,)).fetchall()

print(f"\nMarkets with redeems Jan 17 - Feb 15: {len(redeems_in_period)}")

# For each resolved market, compute full position PnL
resolved_pnl = 0
resolved_details = []
for r in redeems_in_period:
    mid = r["market_id"]
    redeem_amt = float(r["total_redeem"])
    
    # All trades for this market (all-time)
    buy_cost = float(conn.execute(
        "SELECT COALESCE(SUM(total_value),0) FROM wallet_analysis_trade WHERE wallet_id=? AND market_id=? AND side='BUY'",
        (WALLET_ID, mid)).fetchone()[0])
    sell_rev = float(conn.execute(
        "SELECT COALESCE(SUM(total_value),0) FROM wallet_analysis_trade WHERE wallet_id=? AND market_id=? AND side='SELL'",
        (WALLET_ID, mid)).fetchone()[0])
    
    # Also check for splits/merges on this market
    split_cost = float(conn.execute(
        "SELECT COALESCE(SUM(usdc_size),0) FROM wallet_analysis_activity WHERE wallet_id=? AND market_id=? AND activity_type='SPLIT'",
        (WALLET_ID, mid)).fetchone()[0])
    merge_rev = float(conn.execute(
        "SELECT COALESCE(SUM(usdc_size),0) FROM wallet_analysis_activity WHERE wallet_id=? AND market_id=? AND activity_type='MERGE'",
        (WALLET_ID, mid)).fetchone()[0])
    
    pnl = sell_rev + redeem_amt + merge_rev - buy_cost - split_cost
    resolved_pnl += pnl
    if abs(pnl) > 100:
        title = conn.execute("SELECT title FROM wallet_analysis_market WHERE id=?", (mid,)).fetchone()
        resolved_details.append((pnl, mid, title[0] if title else "?", buy_cost, sell_rev, redeem_amt))

print(f"Resolved market PnL (incl splits/merges): ${resolved_pnl:,.2f}")
print(f"Resolved + unrealized: ${resolved_pnl + unrealized:,.2f}")
print(f"Target: $710.14")
print(f"Gap: ${710.14 - (resolved_pnl + unrealized):,.2f}")

# ── What about sells from NON-resolved markets in period? ──
# These are partial sells that realize PnL but market is still open
# Get all markets that had sells in period but NO redeem in period
resolved_market_ids = set(r["market_id"] for r in redeems_in_period)

sells_in_period = conn.execute("""
    SELECT market_id, SUM(total_value) as sell_rev, COUNT(*) as cnt
    FROM wallet_analysis_trade WHERE wallet_id=? AND side='SELL'
    AND datetime >= '2026-01-17' AND datetime < '2026-02-16'
    GROUP BY market_id
""", (WALLET_ID,)).fetchall()

non_resolved_sell_pnl = 0
for s in sells_in_period:
    mid = s["market_id"]
    if mid in resolved_market_ids:
        continue  # already counted in resolved PnL
    sell_rev = float(s["sell_rev"])
    # Need cost basis for these shares
    # Get WACB for this market
    buy_data = conn.execute(
        "SELECT SUM(total_value), SUM(size) FROM wallet_analysis_trade WHERE wallet_id=? AND market_id=? AND side='BUY'",
        (WALLET_ID, mid)).fetchone()
    if buy_data[0] and float(buy_data[1]) > 0:
        wacb = float(buy_data[0]) / float(buy_data[1])
    else:
        wacb = 0
    sell_size = float(conn.execute(
        "SELECT SUM(size) FROM wallet_analysis_trade WHERE wallet_id=? AND market_id=? AND side='SELL' AND datetime >= '2026-01-17' AND datetime < '2026-02-16'",
        (WALLET_ID, mid)).fetchone()[0])
    cost_basis = wacb * sell_size
    pnl = sell_rev - cost_basis
    non_resolved_sell_pnl += pnl

print(f"\nNon-resolved sell PnL in period: ${non_resolved_sell_pnl:,.2f}")
print(f"Total realized in period: ${resolved_pnl + non_resolved_sell_pnl:,.2f}")
print(f"Total + unrealized: ${resolved_pnl + non_resolved_sell_pnl + unrealized:,.2f}")
print(f"Target: $710.14")

# ── Theory A verification ──
# monthly = net_cashflow + portfolio_now - portfolio_start
# Solve for portfolio_start using PM API cashflow
pm_cf = 1886.65  # from PM API
portfolio_start_needed = pm_cf + portfolio_value - 710.14
print(f"\n=== Theory A: Mark-to-market ===")
print(f"PM cashflow: ${pm_cf:,.2f}")
print(f"Portfolio now: ${portfolio_value:,.2f}")
print(f"Portfolio start needed: ${portfolio_start_needed:,.2f}")

# Our DB cashflow
our_cf = 3364.74
our_portfolio_start = our_cf + portfolio_value - 710.14
print(f"Our cashflow: ${our_cf:,.2f}")
print(f"Our portfolio start needed: ${our_portfolio_start:,.2f}")

# ── Try: use PM positions API realizedPnl for monthly calculation ──
# Some of the realizedPnl on current positions may have been realized THIS month
# From sells of partial positions
print(f"\n=== Current position details ===")
for p in sorted(positions, key=lambda x: -float(x.get("realizedPnl", 0)))[:10]:
    rp = float(p.get("realizedPnl", 0))
    cp = float(p.get("cashPnl", 0))
    iv = float(p.get("initialValue", 0))
    cv = float(p.get("currentValue", 0))
    sz = float(p.get("size", 0))
    print(f"  realized=${rp:>8.2f} cash=${cp:>8.2f} init=${iv:>8.2f} curr=${cv:>8.2f} size={sz:>8.2f} {p.get('title','')[:40]}")

# Check: sum of realized from current positions that overlap with our period
# All current positions presumably had activity in the period
print(f"\nRealized from current positions: ${realized_current:,.2f}")
print(f"Unrealized from current positions: ${unrealized:,.2f}")
print(f"Total (current positions only): ${realized_current + unrealized:,.2f}")
print(f"Resolved markets PnL: ${resolved_pnl:,.2f}")
print(f"Grand total: ${resolved_pnl + realized_current + unrealized:,.2f}")
print(f"Target all-time: $20,172.77")

# ── Compute all-time using our DB ──
alltime_buy = float(conn.execute("SELECT SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=? AND side='BUY'", (WALLET_ID,)).fetchone()[0])
alltime_sell = float(conn.execute("SELECT SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=? AND side='SELL'", (WALLET_ID,)).fetchone()[0])
alltime_redeem = float(conn.execute("SELECT COALESCE(SUM(usdc_size),0) FROM wallet_analysis_activity WHERE wallet_id=? AND activity_type='REDEEM'", (WALLET_ID,)).fetchone()[0])
alltime_merge = float(conn.execute("SELECT COALESCE(SUM(usdc_size),0) FROM wallet_analysis_activity WHERE wallet_id=? AND activity_type='MERGE'", (WALLET_ID,)).fetchone()[0])
alltime_split = float(conn.execute("SELECT COALESCE(SUM(usdc_size),0) FROM wallet_analysis_activity WHERE wallet_id=? AND activity_type='SPLIT'", (WALLET_ID,)).fetchone()[0])
alltime_reward = float(conn.execute("SELECT COALESCE(SUM(usdc_size),0) FROM wallet_analysis_activity WHERE wallet_id=? AND activity_type='REWARD'", (WALLET_ID,)).fetchone()[0])

alltime_cf = alltime_sell + alltime_redeem + alltime_merge + alltime_reward - alltime_buy - alltime_split
print(f"\n=== All-time cashflow: ${alltime_cf:,.2f}")
print(f"+ portfolio: ${alltime_cf + portfolio_value:,.2f}")
print(f"Target: $20,172.77")
print(f"Gap: ${20172.77 - (alltime_cf + portfolio_value):,.2f}")

conn.close()
