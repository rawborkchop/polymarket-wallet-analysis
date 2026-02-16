"""
V6: Key insight - PM cashflow from their own API = $1,886.65, not $710.14.
This means PM's monthly PnL is NOT pure cashflow.

Theory: monthly PnL = delta(all-time PnL) = delta(realized + unrealized)
= cashflow_in_period + delta(unrealized)
= $1,886.65 + (unrealized_now - unrealized_30d_ago)

If monthly = $710.14, then delta(unrealized) = $710.14 - $1,886.65 = -$1,176.51
i.e. unrealized PnL decreased by $1,176 during the month (new underwater positions).

Let's verify with current positions data and figure out data discrepancies.
"""
import sqlite3, json, urllib.request, time
from collections import defaultdict
from datetime import datetime

WALLET_ID = 7
ADDR = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
PERIOD_START = datetime(2026, 1, 16)
PERIOD_END = datetime(2026, 2, 16)

# Fetch current leaderboard values
def fetch_lb(period):
    url = f"https://data-api.polymarket.com/v1/leaderboard?timePeriod={period}&orderBy=PNL&limit=1&offset=0&category=overall&user={ADDR}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    return data[0] if data else None

print("=== Current Polymarket Leaderboard ===")
for p in ["all", "month", "week"]:
    lb = fetch_lb(p)
    if lb:
        print(f"  {p:6s}: PnL=${float(lb['pnl']):>12.2f}  Vol=${float(lb['vol']):>12.2f}")

# Fetch positions
url = f"https://data-api.polymarket.com/positions?user={ADDR}&sizeThreshold=0"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=10) as r:
    positions = json.loads(r.read())

print(f"\n=== Current Positions ({len(positions)}) ===")
total_init = sum(float(p.get("initialValue", 0)) for p in positions)
total_curr = sum(float(p.get("currentValue", 0)) for p in positions)
total_realized = sum(float(p.get("realizedPnl", 0)) for p in positions)
total_unrealized = total_curr - total_init
print(f"  initialValue: ${total_init:,.2f}")
print(f"  currentValue: ${total_curr:,.2f}")
print(f"  unrealized (curr-init): ${total_unrealized:,.2f}")
print(f"  sum(realizedPnl): ${total_realized:,.2f}")

# Verify theory: monthly = cashflow + delta(unrealized)
# PM API cashflow in period = $1,886.65 (from PM's own activity data)
pm_cashflow = 1886.65
pm_monthly = 710.14
pm_alltime = 20172.77

print(f"\n=== Theory: monthly = delta(all-time) ===")
print(f"  all-time now: ${pm_alltime:,.2f}")
print(f"  monthly: ${pm_monthly:,.2f}")
print(f"  implied all-time 30d ago: ${pm_alltime - pm_monthly:,.2f}")
print(f"")
print(f"  PM API cashflow: ${pm_cashflow:,.2f}")
print(f"  delta(unrealized) needed: ${pm_monthly - pm_cashflow:,.2f}")
print(f"  current unrealized: ${total_unrealized:,.2f}")
print(f"  implied unrealized 30d ago: ${total_unrealized - (pm_monthly - pm_cashflow):,.2f}")

# ── Check our DB vs PM data discrepancy ──
conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row

print(f"\n=== DB vs PM API data comparison ===")
# Our DB trades in period
db_buy_count = conn.execute("SELECT COUNT(*) FROM wallet_analysis_trade WHERE wallet_id=? AND side='BUY' AND datetime >= '2026-01-16' AND datetime < '2026-02-16'", (WALLET_ID,)).fetchone()[0]
db_sell_count = conn.execute("SELECT COUNT(*) FROM wallet_analysis_trade WHERE wallet_id=? AND side='SELL' AND datetime >= '2026-01-16' AND datetime < '2026-02-16'", (WALLET_ID,)).fetchone()[0]
db_buy_usd = float(conn.execute("SELECT SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=? AND side='BUY' AND datetime >= '2026-01-16' AND datetime < '2026-02-16'", (WALLET_ID,)).fetchone()[0])
db_sell_usd = float(conn.execute("SELECT SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=? AND side='SELL' AND datetime >= '2026-01-16' AND datetime < '2026-02-16'", (WALLET_ID,)).fetchone()[0])
db_redeem_count = conn.execute("SELECT COUNT(*) FROM wallet_analysis_activity WHERE wallet_id=? AND activity_type='REDEEM' AND datetime >= '2026-01-16' AND datetime < '2026-02-16'", (WALLET_ID,)).fetchone()[0]
db_redeem_usd = float(conn.execute("SELECT SUM(usdc_size) FROM wallet_analysis_activity WHERE wallet_id=? AND activity_type='REDEEM' AND datetime >= '2026-01-16' AND datetime < '2026-02-16'", (WALLET_ID,)).fetchone()[0])

print(f"                    Our DB    PM API")
print(f"  Buys (count):     {db_buy_count:>6}    2255")
print(f"  Buys (USDC):   ${db_buy_usd:>10,.2f}  $28,785.50")
print(f"  Sells (count):    {db_sell_count:>6}    500")
print(f"  Sells (USDC):  ${db_sell_usd:>10,.2f}  $10,982.71")
print(f"  Redeems (count):  {db_redeem_count:>6}    338")
print(f"  Redeems (USDC):${db_redeem_usd:>10,.2f}  $19,045.70")
print(f"  DB Cashflow:   ${db_sell_usd + db_redeem_usd + 643.75 - db_buy_usd:>10,.2f}")
print(f"  PM Cashflow:   $  1,886.65")

# Extra trades in our DB
extra_buys = db_buy_count - 2255
extra_sells = db_sell_count - 500
extra_buy_usd = db_buy_usd - 28785.50
extra_sell_usd = db_sell_usd - 10982.71
extra_redeem_usd = db_redeem_usd - 19045.70

print(f"\n  Extra in our DB:")
print(f"  Buys: {extra_buys} trades, ${extra_buy_usd:,.2f}")
print(f"  Sells: {extra_sells} trades, ${extra_sell_usd:,.2f}")
print(f"  Redeems: {db_redeem_count - 338} entries, ${extra_redeem_usd:,.2f}")

# ── Now try to replicate PM's $710 using PM API cashflow approach ──
# PM's monthly PnL formula (hypothesis):
# monthly = sum of (position PnL for positions that RESOLVED in the month)
# where position PnL = (redeem at $1 per winning share) - (total cost basis)
# 
# This is different from cashflow because:
# - Buys for NEW positions (still open) don't count as cost
# - Sells from existing positions DO count as revenue  
# - Only REALIZED events matter

# Let me try: for each market that had a REDEEM in period,
# compute: redeem_amount - (avg_price * redeemed_shares)
# where avg_price comes from buys of the WINNING outcome

print(f"\n=== Method: Redeem PnL only (markets resolved in period) ===")
# For each redeem in period, find the market, find which asset was bought, compute cost basis
redeems_in_period = conn.execute("""
    SELECT market_id, SUM(usdc_size) as total_redeem, MAX(datetime) as dt
    FROM wallet_analysis_activity WHERE wallet_id=? AND activity_type='REDEEM' 
    AND datetime >= '2026-01-16' AND datetime < '2026-02-16'
    AND usdc_size > 0
    GROUP BY market_id
""", (WALLET_ID,)).fetchall()

# For each market, get all trades (all time) and compute cost basis
redeem_pnl = 0
sell_pnl = 0
for r in redeems_in_period:
    mid = r["market_id"]
    redeem_amt = float(r["total_redeem"])
    
    # Get all buys for this market (across all assets)
    buys = conn.execute("""
        SELECT asset, SUM(size) as total_size, SUM(total_value) as total_cost
        FROM wallet_analysis_trade WHERE wallet_id=? AND market_id=? AND side='BUY'
        GROUP BY asset
    """, (WALLET_ID, mid)).fetchall()
    
    sells = conn.execute("""
        SELECT asset, SUM(size) as total_size, SUM(total_value) as total_rev
        FROM wallet_analysis_trade WHERE wallet_id=? AND market_id=? AND side='SELL'
        GROUP BY asset
    """, (WALLET_ID, mid)).fetchall()
    
    total_buy_cost = sum(float(b["total_cost"]) for b in buys)
    total_sell_rev = sum(float(s["total_rev"]) for s in sells)
    
    # Market PnL = sell_rev + redeem - buy_cost
    market_pnl = total_sell_rev + redeem_amt - total_buy_cost
    redeem_pnl += market_pnl

print(f"Redeem-based market PnL: ${redeem_pnl:,.2f}")
print(f"Target: $710.14")

# ── Try: only count sells in period + redeems in period, with FIFO cost basis ──
# For sells in period: realized PnL = sell_price * size - FIFO_cost_basis
# For redeems in period: realized PnL = redeem_usdc - FIFO_cost_basis
print(f"\n=== FIFO realized PnL from events in period ===")
from collections import deque

# Build FIFO lots for all assets (all time, chronologically)
all_trades = conn.execute("""
    SELECT asset, side, price, size, total_value, datetime, market_id
    FROM wallet_analysis_trade WHERE wallet_id=? ORDER BY datetime
""", (WALLET_ID,)).fetchall()

asset_lots = defaultdict(deque)  # asset -> deque of (price, size)
market_for_asset = {}
fifo_monthly_pnl = 0

# First pass: process all trades, realize PnL for sells in period
for t in all_trades:
    aid = t["asset"]
    market_for_asset[aid] = t["market_id"]
    if t["side"] == "BUY":
        asset_lots[aid].append({"price": float(t["price"]), "size": float(t["size"])})
    else:
        sell_price = float(t["price"])
        sell_size = float(t["size"])
        dt = datetime.fromisoformat(t["datetime"])
        in_period = PERIOD_START <= dt < PERIOD_END
        
        while sell_size > 0.0001 and asset_lots[aid]:
            lot = asset_lots[aid][0]
            matched = min(sell_size, lot["size"])
            realized = (sell_price - lot["price"]) * matched
            if in_period:
                fifo_monthly_pnl += realized
            lot["size"] -= matched
            sell_size -= matched
            if lot["size"] < 0.0001:
                asset_lots[aid].popleft()

# Second pass: process redeems in period
redeems = conn.execute("""
    SELECT market_id, usdc_size, datetime
    FROM wallet_analysis_activity WHERE wallet_id=? AND activity_type='REDEEM'
    AND datetime >= '2026-01-16' AND datetime < '2026-02-16' AND usdc_size > 0
    ORDER BY datetime
""", (WALLET_ID,)).fetchall()

# Map market_id to assets
market_to_assets = defaultdict(set)
for aid, mid in market_for_asset.items():
    market_to_assets[mid].add(aid)

for r in redeems:
    mid = r["market_id"]
    usdc = float(r["usdc_size"])
    # Redeem at $1 per winning token
    # Find asset with remaining lots
    for aid in market_to_assets.get(mid, []):
        remaining = sum(l["size"] for l in asset_lots[aid])
        if remaining > 0.5:
            redeem_size = min(remaining, usdc)
            while redeem_size > 0.0001 and asset_lots[aid]:
                lot = asset_lots[aid][0]
                matched = min(redeem_size, lot["size"])
                realized = (1.0 - lot["price"]) * matched
                fifo_monthly_pnl += realized
                lot["size"] -= matched
                redeem_size -= matched
                if lot["size"] < 0.0001:
                    asset_lots[aid].popleft()
            break

print(f"FIFO Monthly PnL: ${fifo_monthly_pnl:,.2f}")
print(f"Target: $710.14")

# ── What about merges in period? ──
merges = conn.execute("""
    SELECT market_id, usdc_size FROM wallet_analysis_activity WHERE wallet_id=?
    AND activity_type='MERGE' AND datetime >= '2026-01-16' AND datetime < '2026-02-16'
""", (WALLET_ID,)).fetchall()
merge_pnl = 0
for m in merges:
    # Merge: return all outcome tokens, get $1 per pair
    # PnL from merge = merge_usdc - cost_basis of merged tokens
    # This is complex... skip for now
    merge_pnl += float(m["usdc_size"])
print(f"Merge USDC in period: ${merge_pnl:,.2f}")

conn.close()
