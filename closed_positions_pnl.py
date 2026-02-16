"""
Closed-position PnL analysis for 1pixel wallet.
Approach: For each asset (token_id), track all buys/sells to compute balance over time.
A position is "closed" when balance reaches ~0.
PnL per position = total_sell_revenue + redeem_revenue - total_buy_cost
"""
import sqlite3
from collections import defaultdict
from datetime import datetime

WALLET_ID = 7
PERIOD_START = datetime(2026, 1, 16)
PERIOD_END = datetime(2026, 2, 16)  # inclusive-ish

conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row

# ── 1. Load all trades for wallet, grouped by asset ──
trades = conn.execute("""
    SELECT asset, side, price, size, total_value, market_id, datetime
    FROM wallet_analysis_trade WHERE wallet_id=?
    ORDER BY datetime
""", (WALLET_ID,)).fetchall()

print(f"Total trades: {len(trades)}")

# Group by asset
assets = defaultdict(lambda: {"buys": [], "sells": [], "market_id": None})
for t in trades:
    a = assets[t["asset"]]
    a["market_id"] = t["market_id"]
    entry = {"price": float(t["price"]), "size": float(t["size"]),
             "total_value": float(t["total_value"]), "dt": t["datetime"]}
    if t["side"] == "BUY":
        a["buys"].append(entry)
    else:
        a["sells"].append(entry)

print(f"Unique assets: {len(assets)}")

# ── 2. Load redeems ──
# Redeems don't have asset info, only market_id and usdc_size
# We need to match redeems to assets via market_id
# For each market, figure out which asset was the winning one
redeems = conn.execute("""
    SELECT market_id, usdc_size, datetime, transaction_hash
    FROM wallet_analysis_activity
    WHERE wallet_id=? AND activity_type='REDEEM' AND usdc_size > 0
    ORDER BY datetime
""", (WALLET_ID,)).fetchall()

print(f"Redeems with usdc > 0: {len(redeems)}")

# Map market_id -> list of assets traded
market_assets = defaultdict(set)
for asset_id, data in assets.items():
    if data["market_id"]:
        market_assets[data["market_id"]].add(asset_id)

# For redeems, we need to know which asset was redeemed
# The winning asset is the one where the user held tokens
# We'll assign redeem to the asset with positive balance at redeem time
# For simplicity: assign to the asset in that market that has net buys > net sells

asset_redeems = defaultdict(list)  # asset_id -> list of {usdc, dt}

for r in redeems:
    mid = r["market_id"]
    usdc = float(r["usdc_size"])
    dt = r["datetime"]
    
    candidates = market_assets.get(mid, set())
    if len(candidates) == 1:
        asset_redeems[list(candidates)[0]].append({"usdc": usdc, "dt": dt})
    elif len(candidates) > 1:
        # Pick the asset with positive net balance
        best = None
        best_bal = 0
        for cid in candidates:
            a = assets[cid]
            bal = sum(e["size"] for e in a["buys"]) - sum(e["size"] for e in a["sells"])
            if bal > best_bal:
                best_bal = bal
                best = cid
        if best:
            asset_redeems[best].append({"usdc": usdc, "dt": dt})
    # else: no trades for this market, skip

# ── 3. For each asset, compute PnL and find close time ──
positions = []
for asset_id, data in assets.items():
    buy_cost = sum(e["total_value"] for e in data["buys"])
    buy_size = sum(e["size"] for e in data["buys"])
    sell_revenue = sum(e["total_value"] for e in data["sells"])
    sell_size = sum(e["size"] for e in data["sells"])
    redeem_usdc = sum(r["usdc"] for r in asset_redeems.get(asset_id, []))
    
    pnl = sell_revenue + redeem_usdc - buy_cost
    net_balance = buy_size - sell_size
    
    # Track when position was closed
    # Walk through events chronologically to find when balance hits ~0
    events = []
    for e in data["buys"]:
        events.append((e["dt"], "BUY", e["size"]))
    for e in data["sells"]:
        events.append((e["dt"], "SELL", e["size"]))
    for r in asset_redeems.get(asset_id, []):
        # Redeem clears the position
        events.append((r["dt"], "REDEEM", 0))
    events.sort()
    
    balance = 0
    close_dt = None
    for dt, side, size in events:
        if side == "BUY":
            balance += size
        elif side == "SELL":
            balance -= size
        elif side == "REDEEM":
            balance = 0  # redeemed
        
        if balance < 0.01 and balance >= -0.01 and close_dt is None and balance != 0 or (side == "REDEEM"):
            close_dt = dt
    
    # If balance is still ~0, it's closed
    is_closed = abs(net_balance) < 0.5 or redeem_usdc > 0
    
    # Final close time: last sell or last redeem
    last_event_dt = None
    if data["sells"]:
        last_event_dt = max(e["dt"] for e in data["sells"])
    redeem_list = asset_redeems.get(asset_id, [])
    if redeem_list:
        last_redeem_dt = max(r["dt"] for r in redeem_list)
        if last_event_dt is None or last_redeem_dt > last_event_dt:
            last_event_dt = last_redeem_dt
    
    positions.append({
        "asset": asset_id[:20],
        "market_id": data["market_id"],
        "buy_cost": buy_cost,
        "sell_revenue": sell_revenue,
        "redeem_usdc": redeem_usdc,
        "pnl": pnl,
        "net_balance": net_balance,
        "is_closed": is_closed,
        "close_dt": last_event_dt,
    })

# ── 4. Compute ALL-TIME PnL (all closed positions) ──
all_time_pnl = sum(p["pnl"] for p in positions if p["is_closed"])
all_time_all = sum(p["pnl"] for p in positions)
total_buy = sum(p["buy_cost"] for p in positions)
total_sell = sum(p["sell_revenue"] for p in positions)
total_redeem = sum(p["redeem_usdc"] for p in positions)

print(f"\n=== ALL-TIME ===")
print(f"Total buy cost: ${total_buy:,.2f}")
print(f"Total sell revenue: ${total_sell:,.2f}")
print(f"Total redeem revenue: ${total_redeem:,.2f}")
print(f"All positions PnL: ${all_time_all:,.2f}")
print(f"Closed positions PnL: ${all_time_pnl:,.2f}")
print(f"Target: ~$20,172")

# ── 5. Monthly PnL (closed in period) ──
monthly_closed = [p for p in positions if p["is_closed"] and p["close_dt"] 
                  and PERIOD_START <= datetime.fromisoformat(p["close_dt"]) < PERIOD_END]
monthly_pnl = sum(p["pnl"] for p in monthly_closed)

print(f"\n=== MONTHLY (Jan 16 - Feb 15, 2026) - Closed positions ===")
print(f"Positions closed in period: {len(monthly_closed)}")
print(f"Monthly PnL: ${monthly_pnl:,.2f}")
print(f"Target: $710.14")

# ── 6. Alt method: revenue in period minus proportional cost ──
# Only count sell/redeem revenue that occurred in the period
# And the proportional buy cost for those shares
monthly_sell_rev = 0
monthly_redeem_rev = 0
monthly_buy_cost_proportional = 0

for asset_id, data in assets.items():
    buy_cost = sum(e["total_value"] for e in data["buys"])
    buy_size = sum(e["size"] for e in data["buys"])
    avg_buy_price = buy_cost / buy_size if buy_size > 0 else 0
    
    # Sells in period
    for e in data["sells"]:
        dt = datetime.fromisoformat(e["dt"])
        if PERIOD_START <= dt < PERIOD_END:
            monthly_sell_rev += e["total_value"]
            monthly_buy_cost_proportional += avg_buy_price * e["size"]
    
    # Redeems in period
    for r in asset_redeems.get(asset_id, []):
        dt = datetime.fromisoformat(r["dt"])
        if PERIOD_START <= dt < PERIOD_END:
            monthly_redeem_rev += r["usdc"]
            # Redeem means we got back the full value; cost was avg_buy_price * redeemed_size
            # But redeem size isn't tracked... use remaining balance at redeem time
            # Approximate: redeem_usdc / 1.0 * avg_buy_price (since redeem is at $1 per share)
            redeemed_shares = r["usdc"]  # $1 per winning share
            monthly_buy_cost_proportional += avg_buy_price * redeemed_shares

alt_monthly_pnl = monthly_sell_rev + monthly_redeem_rev - monthly_buy_cost_proportional

print(f"\n=== MONTHLY ALT (revenue in period - proportional cost) ===")
print(f"Sell revenue in period: ${monthly_sell_rev:,.2f}")
print(f"Redeem revenue in period: ${monthly_redeem_rev:,.2f}")
print(f"Proportional buy cost: ${monthly_buy_cost_proportional:,.2f}")
print(f"Alt Monthly PnL: ${alt_monthly_pnl:,.2f}")
print(f"Target: $710.14")

# ── 7. Show top positions by PnL for debugging ──
monthly_closed.sort(key=lambda p: p["pnl"], reverse=True)
print(f"\n=== Top 10 monthly closed positions ===")
for p in monthly_closed[:10]:
    print(f"  PnL: ${p['pnl']:>10.2f}  Buy: ${p['buy_cost']:>10.2f}  Sell: ${p['sell_revenue']:>10.2f}  Redeem: ${p['redeem_usdc']:>10.2f}  Market: {p['market_id']}")

print(f"\n=== Bottom 10 monthly closed positions ===")
for p in monthly_closed[-10:]:
    print(f"  PnL: ${p['pnl']:>10.2f}  Buy: ${p['buy_cost']:>10.2f}  Sell: ${p['sell_revenue']:>10.2f}  Redeem: ${p['redeem_usdc']:>10.2f}  Market: {p['market_id']}")

# Also check: splits and merges as activities
splits = conn.execute("""
    SELECT SUM(usdc_size) FROM wallet_analysis_activity
    WHERE wallet_id=? AND activity_type='SPLIT'
""", (WALLET_ID,)).fetchone()[0]
merges = conn.execute("""
    SELECT SUM(usdc_size) FROM wallet_analysis_activity
    WHERE wallet_id=? AND activity_type='MERGE'
""", (WALLET_ID,)).fetchone()[0]
conversions = conn.execute("""
    SELECT SUM(usdc_size) FROM wallet_analysis_activity
    WHERE wallet_id=? AND activity_type='CONVERSION'
""", (WALLET_ID,)).fetchone()[0]

print(f"\n=== Other activities ===")
print(f"Splits (USDC): ${float(splits or 0):,.2f}")
print(f"Merges (USDC): ${float(merges or 0):,.2f}")
print(f"Conversions (USDC): ${float(conversions or 0):,.2f}")

conn.close()
