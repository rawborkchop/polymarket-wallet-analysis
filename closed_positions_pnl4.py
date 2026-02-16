"""
V4: Theory - PM's monthly PnL = delta in all-time PnL over the period.
i.e., monthly_pnl = alltime_pnl(now) - alltime_pnl(30_days_ago)

If all-time PnL = sell + redeem + merge - buy - split (excl conversions),
then monthly PnL = events happening in the month that affect this calculation.

This is literally the cashflow in the period (Method 1 from V3).
But we got $3,364 not $710.

UNLESS: conversions ARE included in all-time PnL as costs.
All-time with conv: $-2,257 (too low)
All-time without conv: $19,235 (close to $20,172)

Let me investigate: what if conversions partially offset?
Or: what if PM's PnL includes unrealized gains on open positions?

all-time PnL = realized PnL + unrealized PnL
unrealized = sum of (current_price - avg_buy_price) * size for open positions

Monthly PnL = delta(all-time PnL) = delta(realized) + delta(unrealized)
"""
import sqlite3
from collections import defaultdict
from datetime import datetime
import json
import urllib.request

WALLET_ID = 7
ADDR = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"

conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row

# Try fetching current positions from PM API to get unrealized PnL
try:
    url = f"https://data-api.polymarket.com/positions?user={ADDR}&sizeThreshold=0"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        positions = json.loads(r.read())
    
    total_realized = sum(float(p.get("realizedPnl", 0)) for p in positions)
    total_cash_pnl = sum(float(p.get("cashPnl", 0)) for p in positions)
    total_initial = sum(float(p.get("initialValue", 0)) for p in positions)
    total_current = sum(float(p.get("currentValue", 0)) for p in positions)
    
    print(f"=== PM Positions API ({len(positions)} positions) ===")
    print(f"Sum realizedPnl: ${total_realized:,.2f}")
    print(f"Sum cashPnl: ${total_cash_pnl:,.2f}")
    print(f"Sum initialValue: ${total_initial:,.2f}")
    print(f"Sum currentValue: ${total_current:,.2f}")
    print(f"realizedPnl + cashPnl: ${total_realized + total_cash_pnl:,.2f}")
    
    # Show individual positions
    print(f"\nTop positions by cashPnl:")
    positions.sort(key=lambda p: float(p.get("cashPnl", 0)), reverse=True)
    for p in positions[:5]:
        print(f"  cashPnl=${float(p.get('cashPnl',0)):>8.2f} realized=${float(p.get('realizedPnl',0)):>8.2f} size={float(p.get('size',0)):>8.2f} title={p.get('title','')[:50]}")
    
except Exception as e:
    print(f"API error: {e}")
    positions = []

# Now: compute our all-time realized PnL (cashflow, no conversions)
# And add unrealized from current positions
trades = conn.execute("""
    SELECT side, SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=? GROUP BY side
""", (WALLET_ID,)).fetchall()
buy_cost = sell_rev = 0
for t in trades:
    if t[0] == "BUY": buy_cost = float(t[1])
    else: sell_rev = float(t[1])

acts = conn.execute("""
    SELECT activity_type, SUM(usdc_size) FROM wallet_analysis_activity 
    WHERE wallet_id=? GROUP BY activity_type
""", (WALLET_ID,)).fetchall()
act_sums = {a[0]: float(a[1] or 0) for a in acts}

realized_cf = sell_rev + act_sums.get("REDEEM", 0) + act_sums.get("MERGE", 0) + act_sums.get("REWARD", 0) - buy_cost - act_sums.get("SPLIT", 0)

print(f"\n=== Our realized cashflow (excl conv): ${realized_cf:,.2f}")

# If we add unrealized from current positions
if positions:
    unrealized = sum(float(p.get("currentValue", 0)) - float(p.get("initialValue", 0)) for p in positions)
    print(f"Unrealized from PM API: ${unrealized:,.2f}")
    print(f"Realized + Unrealized: ${realized_cf + unrealized:,.2f}")
    print(f"Target all-time: $20,172.77")
    
    # What about: realized_cf + current_value (portfolio value)?
    cv = sum(float(p.get("currentValue", 0)) for p in positions)
    print(f"Current portfolio value: ${cv:,.2f}")
    print(f"Realized CF + portfolio value: ${realized_cf + cv:,.2f}")

# ── Compute cashflow by date to find delta ──
print(f"\n=== Cumulative cashflow over time ===")
all_events = []

for t in conn.execute("SELECT side, total_value, datetime FROM wallet_analysis_trade WHERE wallet_id=? ORDER BY datetime", (WALLET_ID,)):
    dt = t["datetime"]
    val = float(t["total_value"])
    if t["side"] == "BUY":
        all_events.append((dt, -val))
    else:
        all_events.append((dt, val))

for a in conn.execute("SELECT activity_type, usdc_size, datetime FROM wallet_analysis_activity WHERE wallet_id=? ORDER BY datetime", (WALLET_ID,)):
    usdc = float(a["usdc_size"])
    atype = a["activity_type"]
    if atype == "REDEEM": all_events.append((a["datetime"], usdc))
    elif atype == "MERGE": all_events.append((a["datetime"], usdc))
    elif atype == "SPLIT": all_events.append((a["datetime"], -usdc))
    elif atype == "REWARD": all_events.append((a["datetime"], usdc))
    # Skip conversions

all_events.sort()

cumulative = 0
# Print at key dates
key_dates = ["2026-01-16", "2026-01-17", "2026-02-01", "2026-02-15", "2026-02-16"]
date_values = {}
for dt, val in all_events:
    cumulative += val
    d = dt[:10]
    date_values[d] = cumulative

for d in sorted(date_values.keys()):
    if d in key_dates or d == min(date_values.keys()) or d == max(date_values.keys()):
        print(f"  {d}: ${date_values[d]:,.2f}")

# Print Jan 16 and Feb 15 specifically
jan16 = date_values.get("2026-01-16", 0)
feb15 = date_values.get("2026-02-15", 0)
print(f"\nCashflow at Jan 16: ${jan16:,.2f}")
print(f"Cashflow at Feb 15: ${feb15:,.2f}")
print(f"Delta: ${feb15 - jan16:,.2f}")
print(f"Target monthly: $710.14")

# Also try: what was the cashflow exactly at start of data vs now
first_date = min(date_values.keys())
last_date = max(date_values.keys())
print(f"\nFirst date: {first_date} = ${date_values[first_date]:,.2f}")
print(f"Last date: {last_date} = ${date_values[last_date]:,.2f}")

conn.close()
