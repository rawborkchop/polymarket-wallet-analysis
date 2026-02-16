"""Investigate volume gap and missing trades."""
import sqlite3
import requests

conn = sqlite3.connect("db.sqlite3")
c = conn.cursor()
WALLET_ID = 7
ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"

# Volume: Polymarket likely counts size (shares), not USDC
c.execute("SELECT SUM(size) FROM wallet_analysis_trade WHERE wallet_id=?", (WALLET_ID,))
print(f"Total size (all trades): {c.fetchone()[0]:.2f}")

c.execute("SELECT side, SUM(size), SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=? GROUP BY side", (WALLET_ID,))
for r in c.fetchall():
    print(f"  {r[0]}: size={r[1]:.2f}, total_value={r[2]:.2f}")

# Check: total_value for buys and sells
c.execute("SELECT SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=?", (WALLET_ID,))
print(f"Total traded value (buy+sell): {c.fetchone()[0]:.2f}")

# Maybe Polymarket volume = sum of all total_value (buy+sell) + activities?
# Let's also add split + merge + conversion + redeem
c.execute("SELECT SUM(usdc_size) FROM wallet_analysis_activity WHERE wallet_id=?", (WALLET_ID,))
total_activity = c.fetchone()[0]
print(f"Total activity USDC: {total_activity:.2f}")

# What about size-based volume?
c.execute("SELECT SUM(size) FROM wallet_analysis_trade WHERE wallet_id=?", (WALLET_ID,))
total_size = c.fetchone()[0]
print(f"\nTotal trade size: {total_size:.2f}")

# Check Polymarket profile API for their volume number
try:
    # Try the profile endpoint
    for url in [
        f"https://polymarket.com/api/profile/{ADDRESS}",
        f"https://gamma-api.polymarket.com/users/{ADDRESS}",
    ]:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        print(f"\n{url}: {resp.status_code}")
        if resp.ok:
            data = resp.json()
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, (int, float)):
                        print(f"  {k}: {v}")
                    elif isinstance(v, str) and len(v) < 100:
                        print(f"  {k}: {v}")
except Exception as e:
    print(f"API error: {e}")

# Check how many trades we have vs what Polymarket might have
c.execute("SELECT COUNT(*) FROM wallet_analysis_trade WHERE wallet_id=?", (WALLET_ID,))
print(f"\nTotal trades in DB: {c.fetchone()[0]}")

c.execute("SELECT MIN(datetime), MAX(datetime) FROM wallet_analysis_trade WHERE wallet_id=?", (WALLET_ID,))
r = c.fetchone()
print(f"Trade date range: {r[0]} to {r[1]}")

# Check: are there trades with very small sizes that might be dust?
c.execute("SELECT COUNT(*), SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=? AND total_value < 0.01", (WALLET_ID,))
r = c.fetchone()
print(f"\nDust trades (<$0.01): count={r[0]}, value={r[1]:.6f}")

# What if Polymarket uses size*price for some and total_value for others?
# Let's check: for conversion activities, does the wallet get USDC back?
# A conversion is when you hold multiple outcomes and convert (merge) them
# This IS a cash inflow. But $21K of conversions vs $937 gap means they can't all count.

# NEW THEORY: Polymarket PnL might include unrealized gains
# Unrealized = current_value_of_open_positions - cost_basis_of_open_positions
# Let's calculate cost basis of open positions

print("\n\n=== UNREALIZED GAINS ANALYSIS ===")

# For each market, calculate net position and cost basis
c.execute("""
    SELECT t.market_id, m.title,
           SUM(CASE WHEN t.side='BUY' THEN t.size ELSE 0 END) as bought,
           SUM(CASE WHEN t.side='SELL' THEN t.size ELSE 0 END) as sold,
           SUM(CASE WHEN t.side='BUY' THEN t.total_value ELSE 0 END) as buy_cost,
           SUM(CASE WHEN t.side='SELL' THEN t.total_value ELSE 0 END) as sell_rev
    FROM wallet_analysis_trade t
    JOIN wallet_analysis_market m ON t.market_id = m.id
    WHERE t.wallet_id=?
    GROUP BY t.market_id
""", (WALLET_ID,))

total_unrealized_at_1 = 0  # if all open positions win (worth $1)
total_cost_basis = 0

for r in c.fetchall():
    market_id, title, bought, sold, buy_cost, sell_rev = r
    
    # Check if this market has been redeemed
    c2 = conn.cursor()
    c2.execute("""
        SELECT SUM(size) FROM wallet_analysis_activity 
        WHERE wallet_id=? AND market_id=? AND activity_type IN ('REDEEM', 'MERGE', 'CONVERSION')
    """, (WALLET_ID, market_id))
    redeemed = c2.fetchone()[0] or 0
    
    net = bought - sold - redeemed
    if net > 0.01:
        avg_buy = buy_cost / bought if bought > 0 else 0
        unrealized = net * (1 - avg_buy)  # if wins at $1
        total_unrealized_at_1 += unrealized
        total_cost_basis += net * avg_buy

print(f"Total unrealized gains (if all open win at $1): {total_unrealized_at_1:.2f}")
print(f"Total cost basis of open positions: {total_cost_basis:.2f}")

# What about current market prices? We'd need the API for that.
# But Polymarket PnL is supposed to be ALL-TIME, which usually means realized only.

# Let me try yet another approach: what if we're double-counting some merges/splits?
# Merge: you return YES+NO tokens, get $1 USDC per pair
# Split: you pay $1 USDC, get YES+NO tokens
# These should net out if you split then merge the same amount

c.execute("""
    SELECT activity_type, SUM(usdc_size) 
    FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type IN ('SPLIT', 'MERGE', 'CONVERSION')
    GROUP BY activity_type
""", (WALLET_ID,))
print("\nSplit/Merge/Conversion:")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]:.2f}")

# Net of splits and merges
split = 23766.17
merge = 3844.01
conversion = 21493.24
print(f"\nSplit - Merge = {split - merge:.2f}")
print(f"Split - Merge - Conversion = {split - merge - conversion:.2f}")
print(f"Conversion + Merge - Split = {conversion + merge - split:.2f}")

# THEORY: Conversions ARE effectively merges. So the real formula should be:
# PnL = sell_rev + redeem + (merge + conversion) - buy_cost - split + rewards
# But that gives V2 + conversion + rewards = $40,776, way too high
# 
# Unless conversions are already accounted for in the trade data...
# When you do a conversion/merge, the underlying tokens were bought via trades.
# The PnL from those tokens is: conversion_value - cost_of_tokens_converted
# But in our V2 formula, we count buy_cost for those tokens and conversion as revenue.
# So it should be correct... unless conversions don't actually return USDC?

# Let me check: what does a Polymarket CONVERSION actually do on-chain?
# It might be converting between token types, not to USDC
# In that case, usdc_size is just the notional, not actual USDC flow

print("\n\n=== FINAL THEORY: Check if conversion is token-to-token ===")
print("If conversions are token-to-token swaps (not to USDC), they should be excluded.")
print("In that case, the formula stays at V2 + rewards = $19,283.18")
print(f"Remaining gap: $889.59")

# Could the $889.59 be from open position unrealized gains at current prices?
# Or from a fee rebate / reward program we're not capturing?
# Or from rounding across 15,000+ trades?

# Let's check: what's the average rounding error per trade?
print(f"\nIf the gap is from rounding: ${889.59/15151:.4f} per trade")
print("That's ~$0.06 per trade which seems too high for rounding.")

# Check: are there any other activity types we might have in other wallets but not this one?
c.execute("SELECT DISTINCT activity_type FROM wallet_analysis_activity")
print(f"\nAll activity types across all wallets: {[r[0] for r in c.fetchall()]}")

conn.close()
