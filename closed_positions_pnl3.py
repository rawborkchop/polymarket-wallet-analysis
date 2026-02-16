"""
V3: Try multiple monthly PnL methods. 
Key insight: excluding conversions gives all-time ~$19,235 (close to $20,172).
"""
import sqlite3
from collections import defaultdict
from datetime import datetime

WALLET_ID = 7
PERIOD_START = datetime(2026, 1, 16)
PERIOD_END = datetime(2026, 2, 16)

conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row

trades = conn.execute("""
    SELECT asset, side, price, size, total_value, market_id, datetime
    FROM wallet_analysis_trade WHERE wallet_id=? ORDER BY datetime
""", (WALLET_ID,)).fetchall()

activities = conn.execute("""
    SELECT activity_type, market_id, usdc_size, datetime
    FROM wallet_analysis_activity WHERE wallet_id=? ORDER BY datetime
""", (WALLET_ID,)).fetchall()

# Rewards
rewards = conn.execute("""
    SELECT SUM(usdc_size) FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='REWARD'
""", (WALLET_ID,)).fetchone()[0]
print(f"Total rewards: ${float(rewards or 0):.2f}")

# ── Method 1: Pure cashflow in period ──
buy_in_period = 0
sell_in_period = 0
for t in trades:
    dt = datetime.fromisoformat(t["datetime"])
    if PERIOD_START <= dt < PERIOD_END:
        if t["side"] == "BUY":
            buy_in_period += float(t["total_value"])
        else:
            sell_in_period += float(t["total_value"])

split_in_period = 0
merge_in_period = 0
redeem_in_period = 0
reward_in_period = 0
conv_in_period = 0
for a in activities:
    dt = datetime.fromisoformat(a["datetime"])
    if PERIOD_START <= dt < PERIOD_END:
        usdc = float(a["usdc_size"])
        if a["activity_type"] == "SPLIT": split_in_period += usdc
        elif a["activity_type"] == "MERGE": merge_in_period += usdc
        elif a["activity_type"] == "REDEEM": redeem_in_period += usdc
        elif a["activity_type"] == "REWARD": reward_in_period += usdc
        elif a["activity_type"] == "CONVERSION": conv_in_period += usdc

cf_pnl = (sell_in_period + merge_in_period + redeem_in_period + reward_in_period) - (buy_in_period + split_in_period)
print(f"\n=== Method 1: Cashflow in period ===")
print(f"Buys: ${buy_in_period:,.2f}")
print(f"Sells: ${sell_in_period:,.2f}")
print(f"Splits: ${split_in_period:,.2f}")
print(f"Merges: ${merge_in_period:,.2f}")
print(f"Redeems: ${redeem_in_period:,.2f}")
print(f"Rewards: ${reward_in_period:,.2f}")
print(f"Conversions: ${conv_in_period:,.2f}")
print(f"Cashflow PnL (excl conv): ${cf_pnl:,.2f}")
print(f"Target: $710.14")

# ── Method 2: Market-level closed positions (excl conversions) ──
market_assets_map = defaultdict(set)
markets = defaultdict(lambda: {"buy_cost": 0, "sell_rev": 0, "split_cost": 0, 
                                "merge_rev": 0, "redeem_rev": 0, "reward_rev": 0,
                                "net_tokens": defaultdict(float)})

for t in trades:
    mid = t["market_id"]
    m = markets[mid]
    tv = float(t["total_value"])
    sz = float(t["size"])
    market_assets_map[mid].add(t["asset"])
    if t["side"] == "BUY":
        m["buy_cost"] += tv
        m["net_tokens"][t["asset"]] += sz
    else:
        m["sell_rev"] += tv
        m["net_tokens"][t["asset"]] -= sz

for a in activities:
    mid = a["market_id"]
    m = markets[mid]
    usdc = float(a["usdc_size"])
    if a["activity_type"] == "SPLIT":
        m["split_cost"] += usdc
        for aid in market_assets_map.get(mid, []):
            m["net_tokens"][aid] += usdc
    elif a["activity_type"] == "MERGE":
        m["merge_rev"] += usdc
        for aid in market_assets_map.get(mid, []):
            m["net_tokens"][aid] -= usdc
    elif a["activity_type"] == "REDEEM":
        m["redeem_rev"] += usdc
        for aid in market_assets_map.get(mid, []):
            m["net_tokens"][aid] = 0
    elif a["activity_type"] == "REWARD":
        m["reward_rev"] += usdc

# Find close dates and compute monthly PnL
monthly_pnl_m2 = 0
monthly_count = 0
monthly_details = []

for mid, m in markets.items():
    max_bal = max((abs(v) for v in m["net_tokens"].values()), default=0)
    is_closed = max_bal < 1.0
    
    pnl = (m["sell_rev"] + m["merge_rev"] + m["redeem_rev"] + m["reward_rev"]) - (m["buy_cost"] + m["split_cost"])
    
    # Close date
    close_events = []
    for t in trades:
        if t["market_id"] == mid and t["side"] == "SELL":
            close_events.append(t["datetime"])
    for a in activities:
        if a["market_id"] == mid and a["activity_type"] in ("REDEEM", "MERGE"):
            close_events.append(a["datetime"])
    close_dt = max(close_events) if close_events else None
    
    if is_closed and close_dt:
        dt = datetime.fromisoformat(close_dt)
        if PERIOD_START <= dt < PERIOD_END:
            monthly_pnl_m2 += pnl
            monthly_count += 1
            if abs(pnl) > 50:
                monthly_details.append((pnl, mid, m))

print(f"\n=== Method 2: Market-level closed (excl conv) ===")
print(f"Closed in period: {monthly_count}")
print(f"Monthly PnL: ${monthly_pnl_m2:,.2f}")
print(f"Target: $710.14")

# ── Method 3: Only count redeem PnL (positions that resolved in period) ──
# For each market resolved in period, PnL = redeem - (buy_cost + split_cost for that market)
# But only for markets that had redeems in period
monthly_pnl_m3 = 0
m3_count = 0
for mid, m in markets.items():
    # Check if there was a redeem in period
    redeem_in_p = 0
    has_redeem = False
    for a in activities:
        if a["market_id"] == mid and a["activity_type"] == "REDEEM":
            dt = datetime.fromisoformat(a["datetime"])
            if PERIOD_START <= dt < PERIOD_END:
                redeem_in_p += float(a["usdc_size"])
                has_redeem = True
    if has_redeem:
        pnl = (m["sell_rev"] + m["merge_rev"] + redeem_in_p + m["reward_rev"]) - (m["buy_cost"] + m["split_cost"])
        monthly_pnl_m3 += pnl
        m3_count += 1

print(f"\n=== Method 3: Markets with redeems in period ===")
print(f"Markets: {m3_count}")
print(f"Monthly PnL: ${monthly_pnl_m3:,.2f}")

# ── Method 4: Per-trade realized PnL using FIFO ──
# For each asset, track buy lots. On sell, realize PnL = sell_price - buy_price for each lot
# Monthly = sum of realized PnL from sells+redeems in period
print(f"\n=== Method 4: FIFO realized PnL ===")
from collections import deque

asset_buys = defaultdict(deque)  # asset -> deque of (price, remaining_size)
monthly_realized = 0
alltime_realized = 0

# Include splits: for each asset in market, split adds tokens at effective price
# For binary market split $X: you get X tokens each side. Cost per token = $0.50? No...
# Split $X total cost = $X. If binary, X tokens of Yes + X tokens of No.
# Effective cost: $1 per pair, so $0.50 per Yes token and $0.50 per No token? 
# Actually no. The cost basis for a split is: you paid $X for X tokens of each.
# Per outcome token cost = X/X = $1 per token per outcome? No, total cost is X for 2X tokens...
# Per token cost = $0.50 for binary. But that's weird.
# Actually: split $100 -> 100 Yes + 100 No. Total cost $100. 
# If you sell Yes at $0.60, revenue = $60. Cost basis for 100 Yes = ??? 
# The standard way: cost per outcome = split_amount / num_outcomes for binary = $0.50 per token
# Or: cost per outcome = the pro-rata share

# Let's skip splits for FIFO and just use trades
all_events = []
for t in trades:
    all_events.append({
        "dt": t["datetime"], "asset": t["asset"], "side": t["side"],
        "price": float(t["price"]), "size": float(t["size"]), 
        "total_value": float(t["total_value"]), "market_id": t["market_id"],
        "type": "trade"
    })

# Add splits as buys at $0.50 per token (binary assumption)
for a in activities:
    if a["activity_type"] == "SPLIT":
        mid = a["market_id"]
        usdc = float(a["usdc_size"])
        for aid in market_assets_map.get(mid, []):
            n_outcomes = len(market_assets_map.get(mid, []))
            cost_per = 1.0 / n_outcomes if n_outcomes else 0.5
            all_events.append({
                "dt": a["datetime"], "asset": aid, "side": "BUY",
                "price": cost_per, "size": usdc, "total_value": usdc * cost_per,
                "market_id": mid, "type": "split"
            })
    elif a["activity_type"] == "MERGE":
        mid = a["market_id"]
        usdc = float(a["usdc_size"])
        for aid in market_assets_map.get(mid, []):
            n_outcomes = len(market_assets_map.get(mid, []))
            price_per = 1.0 / n_outcomes if n_outcomes else 0.5
            all_events.append({
                "dt": a["datetime"], "asset": aid, "side": "SELL",
                "price": price_per, "size": usdc, "total_value": usdc * price_per,
                "market_id": mid, "type": "merge"
            })

all_events.sort(key=lambda e: e["dt"])

asset_lots = defaultdict(deque)
fifo_monthly = 0
fifo_alltime = 0

for e in all_events:
    aid = e["asset"]
    if e["side"] == "BUY":
        asset_lots[aid].append({"price": e["price"], "size": e["size"]})
    else:  # SELL
        sell_size = e["size"]
        sell_price = e["price"]
        while sell_size > 0.001 and asset_lots[aid]:
            lot = asset_lots[aid][0]
            matched = min(sell_size, lot["size"])
            realized = (sell_price - lot["price"]) * matched
            fifo_alltime += realized
            dt = datetime.fromisoformat(e["dt"])
            if PERIOD_START <= dt < PERIOD_END:
                fifo_monthly += realized
            lot["size"] -= matched
            sell_size -= matched
            if lot["size"] < 0.001:
                asset_lots[aid].popleft()

# Add redeem PnL: redeem at $1 per token
for a in activities:
    if a["activity_type"] == "REDEEM" and float(a["usdc_size"]) > 0:
        mid = a["market_id"]
        usdc = float(a["usdc_size"])
        dt_str = a["datetime"]
        # Find which asset had remaining balance
        for aid in market_assets_map.get(mid, []):
            remaining = sum(lot["size"] for lot in asset_lots[aid])
            if remaining > 0.5:
                redeem_size = min(remaining, usdc)  # approximate
                # Realize at $1 per token
                while redeem_size > 0.001 and asset_lots[aid]:
                    lot = asset_lots[aid][0]
                    matched = min(redeem_size, lot["size"])
                    realized = (1.0 - lot["price"]) * matched
                    fifo_alltime += realized
                    dt = datetime.fromisoformat(dt_str)
                    if PERIOD_START <= dt < PERIOD_END:
                        fifo_monthly += realized
                    lot["size"] -= matched
                    redeem_size -= matched
                    if lot["size"] < 0.001:
                        asset_lots[aid].popleft()
                break

print(f"FIFO All-time: ${fifo_alltime:,.2f}  (target ~$20,172)")
print(f"FIFO Monthly: ${fifo_monthly:,.2f}  (target $710.14)")

# ── Method 5: Simple - just realized events in period ──
# Monthly = (sells in period + redeems in period) - WACB of those shares
# This is what many platforms show
print(f"\n=== Method 5: WACB realized in period ===")
asset_data = defaultdict(lambda: {"buys": [], "sells_in_period": [], "redeem_in_period": 0})
for t in trades:
    aid = t["asset"]
    if t["side"] == "BUY":
        asset_data[aid]["buys"].append({"price": float(t["price"]), "size": float(t["size"]), "dt": t["datetime"]})
    else:
        dt = datetime.fromisoformat(t["datetime"])
        if PERIOD_START <= dt < PERIOD_END:
            asset_data[aid]["sells_in_period"].append({"price": float(t["price"]), "size": float(t["size"])})

# Redeems in period
for a in activities:
    if a["activity_type"] == "REDEEM" and float(a["usdc_size"]) > 0:
        dt = datetime.fromisoformat(a["datetime"])
        if PERIOD_START <= dt < PERIOD_END:
            mid = a["market_id"]
            usdc = float(a["usdc_size"])
            for aid in market_assets_map.get(mid, []):
                tot_buys = sum(b["size"] for b in asset_data[aid]["buys"])
                tot_sells = sum(s["size"] for s in asset_data[aid].get("sells_all", []))
                # Just add redeem to the first asset with buys
                if tot_buys > 0:
                    asset_data[aid]["redeem_in_period"] += usdc
                    break

wacb_monthly = 0
for aid, d in asset_data.items():
    if not d["sells_in_period"] and d["redeem_in_period"] == 0:
        continue
    # WACB
    total_cost = sum(b["price"] * b["size"] for b in d["buys"])
    total_size = sum(b["size"] for b in d["buys"])
    wacb = total_cost / total_size if total_size > 0 else 0
    
    for s in d["sells_in_period"]:
        wacb_monthly += (s["price"] - wacb) * s["size"]
    
    if d["redeem_in_period"] > 0:
        redeemed_shares = d["redeem_in_period"]  # at $1 per share
        wacb_monthly += (1.0 - wacb) * redeemed_shares

print(f"WACB Monthly: ${wacb_monthly:,.2f}  (target $710.14)")

conn.close()
