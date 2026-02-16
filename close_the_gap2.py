"""Investigate the 1282 zero-value REDEEM activities."""
import sqlite3

conn = sqlite3.connect("db.sqlite3")
conn.row_factory = sqlite3.Row
c = conn.cursor()

WALLET_ID = 7
OFFICIAL_PNL = 20172.77

# How many redeems have size but no usdc_size?
c.execute("""
    SELECT COUNT(*), SUM(size), AVG(size), MIN(size), MAX(size)
    FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='REDEEM' AND (usdc_size IS NULL OR usdc_size = 0)
""", (WALLET_ID,))
r = c.fetchone()
print(f"Zero-value REDEEMs: count={r[0]}, sum(size)={r[1]:.2f}, avg={r[2]:.4f}, min={r[3]}, max={r[4]}")

# For redeems, usdc_size should equal size (redeeming winning shares at $1 each)
# So the missing USDC value = sum of size for those 0-value redeems
missing_redeem = r[1] or 0
print(f"Missing REDEEM value (sum of size): {missing_redeem:.2f}")

# But wait - maybe these are losing redeems (outcome lost, so $0)?
# Check: do they have an outcome field?
c.execute("""
    SELECT outcome, COUNT(*), SUM(size)
    FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='REDEEM' AND (usdc_size IS NULL OR usdc_size = 0)
    GROUP BY outcome
""", (WALLET_ID,))
print("\nZero-value REDEEMs by outcome:")
for r in c.fetchall():
    print(f"  outcome='{r[0]}' count={r[1]} sum(size)={r[2]:.2f}")

# Compare with non-zero redeems
c.execute("""
    SELECT outcome, COUNT(*), SUM(size), SUM(usdc_size)
    FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='REDEEM' AND usdc_size > 0
    GROUP BY outcome
""", (WALLET_ID,))
print("\nNon-zero REDEEMs by outcome:")
for r in c.fetchall():
    print(f"  outcome='{r[0]}' count={r[1]} sum(size)={r[2]:.2f} sum(usdc_size)={r[3]:.2f}")

# Sample some zero-value redeems
c.execute("""
    SELECT size, usdc_size, outcome, title, transaction_hash
    FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='REDEEM' AND (usdc_size IS NULL OR usdc_size = 0)
    LIMIT 10
""", (WALLET_ID,))
print("\nSample zero-value REDEEMs:")
for r in c.fetchall():
    print(f"  size={r[0]}, usdc={r[1]}, outcome='{r[2]}', title='{r[3][:60]}'")

# Now try: V2 + rewards + missing_redeem_value
v2 = 19235.50
reward = 47.68

# Maybe only some of these zero-usdc redeems should count
# Polymarket redeems: winning side gets $1/share, losing side gets $0
# If usdc_size=0, it could be the losing side redeem (worth $0)
# OR it could be a data gap where we didn't capture the USDC value

# Let's check if the non-zero redeems have usdc_size == size (i.e. $1/share)
c.execute("""
    SELECT COUNT(*), SUM(ABS(size - usdc_size))
    FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='REDEEM' AND usdc_size > 0
""", (WALLET_ID,))
r = c.fetchone()
print(f"\nNon-zero redeems: count={r[0]}, total |size-usdc_size| = {r[1]:.4f}")

# So for winning redeems, usdc_size = size. For losing, usdc_size = 0.
# The 1282 zero-value redeems are likely LOSING side redeems -> worth $0. Not the gap.

# Let's look at the gap differently. 
# What about the Polymarket PnL formula including unrealized gains?
# Or what about fees?

# Check: do trades have a fee field?
c.execute("PRAGMA table_info(wallet_analysis_trade)")
print(f"\nTrade columns: {[r[1] for r in c.fetchall()]}")

# What if Polymarket calculates PnL differently? 
# Their formula might be: sum of (sell_price - buy_price) * size for each position
# Plus realized gains from redeems

# Let's check the conversion activities more carefully
# CONVERSION might be like a partial redeem where you get back some USDC
c.execute("""
    SELECT COUNT(*), SUM(usdc_size), SUM(size)
    FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='CONVERSION'
""", (WALLET_ID,))
r = c.fetchone()
print(f"\nCONVERSION: count={r[0]}, sum(usdc_size)={r[1]:.2f}, sum(size)={r[2]:.2f}")

# Conversions: usdc_size == size always?
c.execute("""
    SELECT COUNT(*), SUM(ABS(size - usdc_size))
    FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='CONVERSION'
""", (WALLET_ID,))
r = c.fetchone()
print(f"  |size-usdc_size| total = {r[1]:.4f}")

# CONVERSION is like MERGE - you convert conditional tokens back to USDC
# But we already count MERGE. Is CONVERSION double-counted with something?

# Let's think about what Polymarket's PnL actually includes:
# PnL = current_portfolio_value + total_withdrawn - total_deposited
# Or: PnL = realized_gains + unrealized_gains

# Do we have open positions? Check net position per market
print("\n\nChecking if there are open (unredeemed) positions...")
c.execute("""
    SELECT m.title, 
           SUM(CASE WHEN t.side='BUY' THEN t.size ELSE 0 END) as bought,
           SUM(CASE WHEN t.side='SELL' THEN t.size ELSE 0 END) as sold
    FROM wallet_analysis_trade t
    JOIN wallet_analysis_market m ON t.market_id = m.id
    WHERE t.wallet_id=?
    GROUP BY t.market_id
    HAVING (bought - sold) > 0.01
    ORDER BY (bought - sold) DESC
    LIMIT 20
""", (WALLET_ID,))
print("Top open positions (bought > sold):")
total_open = 0
for r in c.fetchall():
    net = r[1] - r[2]
    total_open += net
    if net > 1:
        print(f"  net={net:8.2f}  bought={r[1]:8.2f}  sold={r[2]:8.2f}  {r[0][:50]}")
print(f"Total open position size: {total_open:.2f}")

# But we need to subtract redeemed shares from open positions
# Net position = bought - sold - redeemed (for that market)

# Actually let me try: what if the gap is simply rewards ($47.68) + something related to 
# rounding or conversion profit?

# Let me check: what's the ACTUAL gap after adding rewards?
gap_after_rewards = OFFICIAL_PNL - (v2 + reward)
print(f"\nGap after rewards: {gap_after_rewards:.2f}")
print(f"This is ${gap_after_rewards:.2f} unaccounted for")

# Could this be from conversions being partially profitable?
# In a conversion, you might convert shares worth < $1 each back to $1
# The profit would be: conversion_usdc - cost_of_converted_shares
# But we already track buy cost... hmm

# What about the SELL trades using price*size vs total_value?
c.execute("""
    SELECT SUM(total_value), SUM(price * size), SUM(total_value - price * size)
    FROM wallet_analysis_trade WHERE wallet_id=? AND side='SELL'
""", (WALLET_ID,))
r = c.fetchone()
print(f"\nSELL: total_value={r[0]:.2f}, price*size={r[1]:.2f}, diff={r[2]:.6f}")

c.execute("""
    SELECT SUM(total_value), SUM(price * size), SUM(total_value - price * size)
    FROM wallet_analysis_trade WHERE wallet_id=? AND side='BUY'
""", (WALLET_ID,))
r = c.fetchone()
print(f"BUY:  total_value={r[0]:.2f}, price*size={r[1]:.2f}, diff={r[2]:.6f}")

conn.close()
