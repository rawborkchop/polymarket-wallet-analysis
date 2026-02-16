"""
V2: Include splits as buy cost, merges as sell revenue.
Conversions need investigation - they might be split+sell combos.
"""
import sqlite3
from collections import defaultdict
from datetime import datetime

WALLET_ID = 7
PERIOD_START = datetime(2026, 1, 16)
PERIOD_END = datetime(2026, 2, 16)

conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row

# Load all trades
trades = conn.execute("""
    SELECT asset, side, price, size, total_value, market_id, datetime
    FROM wallet_analysis_trade WHERE wallet_id=? ORDER BY datetime
""", (WALLET_ID,)).fetchall()

# Load all activities
activities = conn.execute("""
    SELECT activity_type, market_id, usdc_size, datetime, asset, outcome
    FROM wallet_analysis_activity WHERE wallet_id=? ORDER BY datetime
""", (WALLET_ID,)).fetchall()

# Group trades by asset
assets = defaultdict(lambda: {"buys": [], "sells": [], "market_id": None, "splits": [], "merges": [], "redeems": []})
market_assets = defaultdict(set)

for t in trades:
    a = assets[t["asset"]]
    a["market_id"] = t["market_id"]
    market_assets[t["market_id"]].add(t["asset"])
    entry = {"price": float(t["price"]), "size": float(t["size"]),
             "total_value": float(t["total_value"]), "dt": t["datetime"]}
    if t["side"] == "BUY":
        a["buys"].append(entry)
    else:
        a["sells"].append(entry)

# For splits: they create tokens on ALL outcomes of a market
# Split $X means you get X tokens of each outcome
# This is like buying each outcome at $1/N (for N outcomes), but total cost is X
# For a binary market: split $100 = 100 Yes + 100 No tokens, cost = $100
# Each outcome gets tokens worth $100/2 = $50 of buy cost? No...
# Actually, split $100 means $100 total cost, and you own both sides
# For PnL per asset: attribute split cost proportionally? Or assign to each asset?
# PM likely assigns: each asset from split gets size tokens at effective cost of $1 per token pair
# For binary: split $X creates X tokens of each. Cost per outcome = can't really split it.

# Let's try: for each market with splits, distribute split USDC equally among assets
# OR: try a market-level approach instead of asset-level

# Let's do MARKET-level PnL
markets = defaultdict(lambda: {"buy_cost": 0, "sell_rev": 0, "split_cost": 0, "merge_rev": 0, 
                                "redeem_rev": 0, "conversion_cost": 0, "last_close_dt": None,
                                "net_tokens": defaultdict(float), "title": ""})

for t in trades:
    m = markets[t["market_id"]]
    tv = float(t["total_value"])
    sz = float(t["size"])
    if t["side"] == "BUY":
        m["buy_cost"] += tv
        m["net_tokens"][t["asset"]] += sz
    else:
        m["sell_rev"] += tv
        m["net_tokens"][t["asset"]] -= sz

for a in activities:
    mid = a["market_id"]
    usdc = float(a["usdc_size"])
    m = markets[mid]
    if a["activity_type"] == "SPLIT":
        m["split_cost"] += usdc
        # Add tokens to all assets in this market
        for asset_id in market_assets.get(mid, []):
            m["net_tokens"][asset_id] += usdc  # split creates `usdc` tokens of each
    elif a["activity_type"] == "MERGE":
        m["merge_rev"] += usdc
        for asset_id in market_assets.get(mid, []):
            m["net_tokens"][asset_id] -= usdc
    elif a["activity_type"] == "REDEEM":
        m["redeem_rev"] += usdc
        # Redeem clears tokens
        for asset_id in market_assets.get(mid, []):
            m["net_tokens"][asset_id] = 0
    elif a["activity_type"] == "CONVERSION":
        m["conversion_cost"] += usdc
        # Conversion: split USDC into tokens then sell one side on another market
        # This creates tokens similar to split
        for asset_id in market_assets.get(mid, []):
            m["net_tokens"][asset_id] += usdc

# Get market titles
titles = dict(conn.execute("SELECT id, title FROM wallet_analysis_market").fetchall())

# Compute market PnL
all_time_pnl = 0
monthly_pnl = 0
monthly_count = 0

for mid, m in markets.items():
    # Total outflow (cost): buy_cost + split_cost + conversion_cost
    # Total inflow (revenue): sell_rev + merge_rev + redeem_rev
    total_cost = m["buy_cost"] + m["split_cost"] + m["conversion_cost"]
    total_rev = m["sell_rev"] + m["merge_rev"] + m["redeem_rev"]
    pnl = total_rev - total_cost
    
    # Is position closed? Check if all token balances are ~0
    max_bal = max(abs(v) for v in m["net_tokens"].values()) if m["net_tokens"] else 0
    is_closed = max_bal < 1.0
    
    # Find close date: last sell, merge, or redeem in this market
    close_events = []
    for t in trades:
        if t["market_id"] == mid and t["side"] == "SELL":
            close_events.append(t["datetime"])
    for a in activities:
        if a["market_id"] == mid and a["activity_type"] in ("REDEEM", "MERGE"):
            close_events.append(a["datetime"])
    
    close_dt = max(close_events) if close_events else None
    
    all_time_pnl += pnl
    
    if is_closed and close_dt:
        dt = datetime.fromisoformat(close_dt)
        if PERIOD_START <= dt < PERIOD_END:
            monthly_pnl += pnl
            monthly_count += 1

print(f"Markets: {len(markets)}")
print(f"\n=== ALL-TIME (all markets) ===")
total_buy = sum(m["buy_cost"] for m in markets.values())
total_sell = sum(m["sell_rev"] for m in markets.values())
total_split = sum(m["split_cost"] for m in markets.values())
total_merge = sum(m["merge_rev"] for m in markets.values())
total_redeem = sum(m["redeem_rev"] for m in markets.values())
total_conv = sum(m["conversion_cost"] for m in markets.values())
print(f"Buy cost: ${total_buy:,.2f}")
print(f"Split cost: ${total_split:,.2f}")
print(f"Conversion cost: ${total_conv:,.2f}")
print(f"Sell revenue: ${total_sell:,.2f}")
print(f"Merge revenue: ${total_merge:,.2f}")
print(f"Redeem revenue: ${total_redeem:,.2f}")
print(f"All-time PnL: ${all_time_pnl:,.2f}")
print(f"Target: ~$20,172")

print(f"\n=== MONTHLY (Jan 16 - Feb 15) ===")
print(f"Closed markets: {monthly_count}")
print(f"Monthly PnL: ${monthly_pnl:,.2f}")
print(f"Target: $710.14")

# Try: simple cash flow (no position tracking)
# PnL = all revenue - all cost
simple_pnl = (total_sell + total_merge + total_redeem) - (total_buy + total_split + total_conv)
print(f"\n=== Simple cash flow PnL: ${simple_pnl:,.2f} ===")
# Without conversions (maybe conversions are neutral?)
no_conv_pnl = (total_sell + total_merge + total_redeem) - (total_buy + total_split)
print(f"Without conv cost: ${no_conv_pnl:,.2f}")
# Conversions as revenue?
conv_rev_pnl = (total_sell + total_merge + total_redeem + total_conv) - (total_buy + total_split)
print(f"Conv as revenue: ${conv_rev_pnl:,.2f}")

conn.close()
