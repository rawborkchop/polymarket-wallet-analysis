"""
Close the ~$937 gap between our PnL calculation and Polymarket's official number.

Polymarket profile data (from /api/profile/volume):
  - volume (amount): $773,199.66 (= sum of all trade sizes)
  - pnl: $20,172.77
  - realized: 0, unrealized: 0

Our V2 cash flow:
  PnL = sell_revenue + redeem + merge - buy_cost - split = $19,235.50
  Gap = $937.27

After rewards ($47.68): gap = $889.59
"""
import sqlite3
import json

conn = sqlite3.connect("db.sqlite3")
conn.row_factory = sqlite3.Row
c = conn.cursor()

WALLET_ID = 7
OFFICIAL_PNL = 20172.77
OFFICIAL_VOLUME = 773199.66

print("=" * 70)
print("1. BASELINE NUMBERS")
print("=" * 70)

c.execute("SELECT side, SUM(total_value), SUM(size) FROM wallet_analysis_trade WHERE wallet_id=? GROUP BY side", (WALLET_ID,))
trade_data = {}
for r in c.fetchall():
    trade_data[r[0]] = {'value': r[1], 'size': r[2]}
    print(f"  {r[0]:5s}: total_value={r[1]:12.2f}  size={r[2]:12.2f}")

c.execute("SELECT activity_type, SUM(usdc_size), SUM(size), COUNT(*) FROM wallet_analysis_activity WHERE wallet_id=? GROUP BY activity_type", (WALLET_ID,))
act_data = {}
for r in c.fetchall():
    act_data[r[0]] = {'usdc': r[1] or 0, 'size': r[2] or 0, 'count': r[3]}
    print(f"  {r[0]:12s}: usdc_size={r[1] or 0:12.2f}  size={r[2] or 0:12.2f}  count={r[3]}")

buy_cost = trade_data['BUY']['value']
sell_rev = trade_data['SELL']['value']
buy_size = trade_data['BUY']['size']
sell_size = trade_data['SELL']['size']
redeem = act_data.get('REDEEM', {}).get('usdc', 0)
merge = act_data.get('MERGE', {}).get('usdc', 0)
split = act_data.get('SPLIT', {}).get('usdc', 0)
reward = act_data.get('REWARD', {}).get('usdc', 0)
conversion = act_data.get('CONVERSION', {}).get('usdc', 0)

v2 = sell_rev + redeem + merge - buy_cost - split
print(f"\n  V2 = {v2:.2f}")
print(f"  V2 + rewards = {v2 + reward:.2f}")

print(f"\n  Volume (sum of size): {buy_size + sell_size:.2f}")
print(f"  Official volume:      {OFFICIAL_VOLUME:.2f}")
print(f"  Volume gap:           {OFFICIAL_VOLUME - buy_size - sell_size:.2f}")

print("\n" + "=" * 70)
print("2. INVESTIGATE: What makes up the $889.59 gap?")
print("=" * 70)

gap = OFFICIAL_PNL - v2 - reward
print(f"  Remaining gap: ${gap:.2f}")

# Theory 1: Polymarket uses size-based (shares) calculation, not USDC
# Their volume = sum of sizes = 771,862 (ours) vs 773,200 (theirs)
# Missing ~1,337 in share volume
# If those are SELL trades: missing_sell_revenue = missing_shares * avg_sell_price
avg_sell_price = sell_rev / sell_size if sell_size > 0 else 0
print(f"\n  Theory 1: Missing trades")
print(f"    Volume gap: {OFFICIAL_VOLUME - buy_size - sell_size:.2f} shares")
print(f"    Avg sell price: {avg_sell_price:.4f}")

# Theory 2: Polymarket PnL includes position-level gains
# PnL per position = (sell_rev + redeem) - buy_cost, but calculated differently
# Maybe they use FIFO cost basis instead of total cost

# Theory 3: Polymarket includes open position unrealized gains
# From /positions API: current open positions worth $20.29
# Cost basis of open positions needs calculation

# Theory 4: The PnL chart uses a cumulative method based on position changes
# Let's look at the PnL chart - last value is 20172.771

# Let's try to reverse-engineer: what if PnL = sum of (cashPnl) for all positions?
# From the positions API, closed positions have cashPnl too
# Let's fetch ALL positions including closed ones

print("\n" + "=" * 70)
print("3. POSITION-BASED ANALYSIS")
print("=" * 70)

# Calculate per-market PnL
c.execute("""
    SELECT t.market_id, t.asset, t.outcome,
           SUM(CASE WHEN t.side='BUY' THEN t.size ELSE 0 END) as bought,
           SUM(CASE WHEN t.side='SELL' THEN t.size ELSE 0 END) as sold,
           SUM(CASE WHEN t.side='BUY' THEN t.total_value ELSE 0 END) as buy_cost,
           SUM(CASE WHEN t.side='SELL' THEN t.total_value ELSE 0 END) as sell_rev
    FROM wallet_analysis_trade t
    WHERE t.wallet_id=?
    GROUP BY t.market_id, t.asset, t.outcome
""", (WALLET_ID,))

positions = []
for r in c.fetchall():
    market_id, asset, outcome = r[0], r[1], r[2]
    bought, sold, bc, sr = r[3], r[4], r[5], r[6]
    
    # Get activities for this specific market+asset
    c2 = conn.cursor()
    c2.execute("""
        SELECT activity_type, SUM(usdc_size), SUM(size) 
        FROM wallet_analysis_activity
        WHERE wallet_id=? AND market_id=?
        GROUP BY activity_type
    """, (WALLET_ID, market_id))
    acts = {row[0]: {'usdc': row[1] or 0, 'size': row[2] or 0} for row in c2.fetchall()}
    
    positions.append({
        'market_id': market_id,
        'asset': asset,
        'outcome': outcome,
        'bought': bought,
        'sold': sold,
        'buy_cost': bc,
        'sell_rev': sr,
        'redeem': acts.get('REDEEM', {}).get('usdc', 0),
        'merge': acts.get('MERGE', {}).get('usdc', 0),
        'split': acts.get('SPLIT', {}).get('usdc', 0),
        'conversion': acts.get('CONVERSION', {}).get('usdc', 0),
    })

# Calculate total PnL different ways
total_v2 = sum(p['sell_rev'] + p['redeem'] + p['merge'] - p['buy_cost'] - p['split'] for p in positions)
print(f"  Per-position V2 sum: {total_v2:.2f}")

# What if Polymarket treats each position's PnL as:
# cashPnl = sell_revenue + redeem_value - initial_cost_of_held_shares
# Where initial cost = avg_price * shares_bought (for the shares you still hold or sold)

# Let's try: Polymarket-style cashPnl
# For each position:
# - You bought X shares at various prices (total cost = buy_cost) 
# - You sold Y shares (revenue = sell_rev)
# - You redeemed Z shares at $1 each (revenue = Z)
# - cashPnl = sell_rev + redeem - buy_cost (ignoring splits/merges)

total_simple = sum(p['sell_rev'] + p['redeem'] - p['buy_cost'] for p in positions)
print(f"  Simple (sell+redeem-buy): {total_simple:.2f}")
print(f"  + split-merge net: {total_simple + sum(p['merge'] - p['split'] for p in positions):.2f}")

# What if we ignore splits and merges entirely?
print(f"  Ignoring splits/merges: {total_simple:.2f}")
print(f"  + rewards: {total_simple + reward:.2f}")
print(f"  Gap: {OFFICIAL_PNL - total_simple - reward:.2f}")

# What about including conversions as equivalent to redeems?
total_with_conv = sum(p['sell_rev'] + p['redeem'] + p['conversion'] - p['buy_cost'] for p in positions)
print(f"  With conversions (sell+redeem+conv-buy): {total_with_conv:.2f}")

print("\n" + "=" * 70)
print("4. SPLIT/MERGE/CONVERSION DEEP DIVE")
print("=" * 70)

# Splits create tokens (cost USDC). Merges destroy tokens (return USDC).
# Conversions might be market-to-market token swaps.
# In cash flow: split is outflow, merge is inflow.
# But if Polymarket tracks per-position: 
#   Split increases your position size (and cost basis)
#   Merge decreases your position (and returns cash)

# If Polymarket's PnL formula is just: all_cash_in - all_cash_out + current_position_value
# cash_in = sell_rev + redeem + merge + conversion? + rewards
# cash_out = buy_cost + split
# current_value = value of open positions

# From the Polymarket /positions API, current value = $20.29
current_value = 20.29

formulas = {
    'V2 (sell+redeem+merge-buy-split)': v2,
    'V2 + rewards': v2 + reward,
    'V2 + rewards + current_value': v2 + reward + current_value,
    'Simple (sell+redeem-buy) + rewards': total_simple + reward,
    'Simple + rewards + merge - split': total_simple + reward + merge - split,
    'sell+redeem+merge+conv-buy-split + rewards': v2 + conversion + reward,
    'Net cash + unrealized': v2 + reward + current_value,
}

print(f"\n  {'Formula':<55s} {'PnL':>10s} {'Gap':>10s}")
print(f"  {'-'*55} {'-'*10} {'-'*10}")
for name, val in sorted(formulas.items(), key=lambda x: abs(x[1] - OFFICIAL_PNL)):
    gap = val - OFFICIAL_PNL
    marker = ' <-- CLOSEST' if abs(gap) == min(abs(v - OFFICIAL_PNL) for v in formulas.values()) else ''
    print(f"  {name:<55s} {val:>10.2f} {gap:>+10.2f}{marker}")

print("\n" + "=" * 70)
print("5. WHAT IF WE'RE MISSING SOME REWARD/ACTIVITY DATA?")
print("=" * 70)

# Check total rewards from API vs our DB
print(f"  Rewards in DB: {reward:.2f} ({act_data.get('REWARD', {}).get('count', 0)} entries)")
print(f"  Gap after V2+rewards: {OFFICIAL_PNL - v2 - reward:.2f}")
print(f"  If gap is entirely from missing rewards: need ${OFFICIAL_PNL - v2 - reward:.2f} more in rewards")

# Check: what are the reward transactions?
c.execute("""
    SELECT datetime, usdc_size, title, transaction_hash 
    FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='REWARD'
    ORDER BY timestamp
""", (WALLET_ID,))
print("\n  All REWARD activities:")
for r in c.fetchall():
    print(f"    {r[0]}  ${r[1]:.4f}  {r[2][:40] if r[2] else 'N/A'}  tx={r[3][:20]}...")

# Check date range of our data vs account join date (2025-02-03)
c.execute("SELECT MIN(timestamp), MAX(timestamp) FROM wallet_analysis_trade WHERE wallet_id=?", (WALLET_ID,))
r = c.fetchone()
print(f"\n  Trade timestamp range: {r[0]} - {r[1]}")

c.execute("SELECT MIN(timestamp), MAX(timestamp) FROM wallet_analysis_activity WHERE wallet_id=?", (WALLET_ID,))
r = c.fetchone()
print(f"  Activity timestamp range: {r[0]} - {r[1]}")

print("\n" + "=" * 70)
print("6. POLYMARKET PnL FORMULA HYPOTHESIS")  
print("=" * 70)
print("""
  Polymarket likely calculates PnL as a running sum of position-level gains:
  
  For each trade event:
    BUY:  no PnL impact (increases position, cost basis goes up)
    SELL: PnL += sell_price * size - avg_cost * size (realized gain)
    REDEEM (win): PnL += (1 - avg_cost) * size (realized gain)  
    REDEEM (loss): PnL += (0 - avg_cost) * size (realized loss, but cost already sunk)
  
  This FIFO/avg cost method may differ from our simple cash flow.
  
  Key difference: In cash flow, splits/merges affect the total.
  In position-tracking, splits just add to position size at $1 cost,
  and merges reduce position + return $1.
  
  If they track it as: PnL = sum of realized gains per trade,
  then splits/merges are neutral (buy at $1, merge at $1 = 0 PnL).
  
  This means their formula might effectively be:
  PnL = sell_revenue + redeem_revenue - buy_cost + rewards + open_position_unrealized
  (where buy_cost already includes splits as "buys at $1")
""")

# Test: PnL = sell_rev + redeem - buy_cost + rewards
# But wait, we need to handle splits differently
# When you split: you pay $X USDC, get tokens worth $X
# When you merge: you return tokens, get $X USDC
# In Polymarket's view, split might not be a "trade" that affects buy_cost
# It might be separate

# So their formula could be:
# PnL = (sell_rev - buy_cost_of_sold_shares) + (redeem_rev - buy_cost_of_redeemed_shares) + unrealized
# Which equals: sell_rev + redeem - total_buy_cost + remaining_position_value + rewards

# The issue is: are splits counted in buy_cost in our data?
# If YES: then V2 already handles it correctly (split cost is separate)
# If NO: then we need to add split cost

# Let's check: are there trades that correspond to splits?
c.execute("""
    SELECT COUNT(*) FROM wallet_analysis_trade t
    WHERE t.wallet_id=? AND t.side='BUY' AND t.price >= 0.99
""", (WALLET_ID,))
buys_at_1 = c.fetchone()[0]
print(f"\n  BUY trades with price >= $0.99: {buys_at_1}")

c.execute("""
    SELECT COUNT(*) FROM wallet_analysis_trade t
    WHERE t.wallet_id=? AND t.side='BUY' AND t.price = 1.0
""", (WALLET_ID,))
buys_exact_1 = c.fetchone()[0]
print(f"  BUY trades with price = $1.00: {buys_exact_1}")

# If splits generate BUY trades at $1, they'd be in buy_cost already
# In that case we should NOT subtract split_cost separately

# Let's test: V2 WITHOUT split and merge
v2_no_split_merge = sell_rev + redeem - buy_cost
print(f"\n  V2 without split/merge: {v2_no_split_merge:.2f}")
print(f"  + rewards: {v2_no_split_merge + reward:.2f}")
print(f"  Gap: {OFFICIAL_PNL - v2_no_split_merge - reward:.2f}")

# That gives a very different number. Let's see if split_cost == merge_cost roughly
print(f"\n  Split cost: {split:.2f}")
print(f"  Merge revenue: {merge:.2f}")
print(f"  Split - Merge: {split - merge:.2f}")
print(f"  Conversion: {conversion:.2f}")
print(f"  Split - Merge - Conversion: {split - merge - conversion:.2f}")

# INTERESTING: Split - Merge - Conversion = -1571.08
# This means conversions+merges EXCEEDED splits by $1,571
# If we remove split/merge/conversion from the formula:
# V2_no_sm = sell + redeem - buy = different from V2 by (merge - split) = negative
# So V2_no_sm = V2 - merge + split = 19235.50 - 3844.01 + 23766.17 = 39157.66
# That doesn't help

print("\n" + "=" * 70)
print("7. FINAL ANALYSIS: EXPLORE CONVERSION AS PARTIAL INFLOW")
print("=" * 70)

# What if conversions are partially inflows?
# Conversion happens when you hold ALL outcomes of a multi-outcome market
# and convert to a single outcome. It's like a partial merge.
# The USDC value might represent the "value returned" minus "value spent"
# Or it might be the full notional of tokens converted.

# Key test: does conversion + merge - split explain the gap?
conv_net = conversion + merge - split  # = 1571.08
print(f"  Conversion + Merge - Split = {conv_net:.2f}")
print(f"  V2 + rewards + conv_net = {v2 + reward + conv_net:.2f}")
print(f"  Gap: {OFFICIAL_PNL - v2 - reward - conv_net:.2f}")

# Hmm, that gives 20854.26, overshooting by $681.49
# What if only some fraction of conversions count?

# What fraction of conversion would close the gap?
needed = OFFICIAL_PNL - v2 - reward  # 889.59
print(f"\n  Need: ${needed:.2f} to close gap")
print(f"  If from conversions: {needed/conversion*100:.1f}% of conversion value")
print(f"  If from conv_net: {needed/conv_net*100:.1f}% of conv_net")

# Or: what if the gap = rewards we haven't captured?
# Polymarket has liquidity mining rewards, trading rewards, etc.
# $889.59 in uncaptured rewards over 1 year of trading is plausible

# Let's check: what period are rewards from?
c.execute("""
    SELECT MIN(datetime), MAX(datetime), COUNT(*), SUM(usdc_size)
    FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='REWARD'
""", (WALLET_ID,))
r = c.fetchone()
print(f"\n  Rewards: {r[0]} to {r[1]}, {r[2]} entries, ${r[3]:.2f}")
print(f"  Average reward: ${r[3]/r[2]:.2f}")
print(f"  Rewards/month estimate: ~${r[3]/12:.2f}")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"""
  Official PnL:          ${OFFICIAL_PNL:,.2f}
  Our V2 cash flow:      ${v2:,.2f}
  + Rewards ({reward:.2f}):   ${v2 + reward:,.2f}
  Remaining gap:         ${OFFICIAL_PNL - v2 - reward:,.2f}
  
  Volume match: {buy_size + sell_size:,.2f} vs {OFFICIAL_VOLUME:,.2f} 
    (diff: {OFFICIAL_VOLUME - buy_size - sell_size:,.2f} = {(OFFICIAL_VOLUME - buy_size - sell_size)/(buy_size + sell_size)*100:.2f}%)
  
  BEST HYPOTHESIS: The ${OFFICIAL_PNL - v2 - reward:.2f} gap is likely from:
  1. Missing/uncaptured rewards (liquidity mining, trading incentives)
  2. Slight differences in how Polymarket handles multi-outcome 
     market conversions (they return USDC, we might not capture all)
  3. Rounding/precision across 15,000+ trades
  
  The closest formula we can achieve:
    PnL = sell + redeem + merge - buy - split + rewards = ${v2 + reward:,.2f}
    Error: {abs(OFFICIAL_PNL - v2 - reward)/OFFICIAL_PNL*100:.2f}% from official
""")

conn.close()
