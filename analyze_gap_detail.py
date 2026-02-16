"""Deep analysis of the $889 gap. Check if PM counts resolved-but-unredeemed differently."""
import sqlite3

WALLET_ID = 7
OFFICIAL_PNL = 20172.77

conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()

# Cash flow components
c.execute("SELECT side, SUM(total_value) FROM wallet_analysis_trade WHERE wallet_id=? GROUP BY side", (WALLET_ID,))
trade_sums = dict(c.fetchall())
c.execute("SELECT activity_type, SUM(usdc_size) FROM wallet_analysis_activity WHERE wallet_id=? GROUP BY activity_type", (WALLET_ID,))
act_sums = dict(c.fetchall())

buy = trade_sums.get('BUY', 0)
sell = trade_sums.get('SELL', 0)
redeem = act_sums.get('REDEEM', 0)
merge = act_sums.get('MERGE', 0)
split = act_sums.get('SPLIT', 0)
reward = act_sums.get('REWARD', 0)
conversion = act_sums.get('CONVERSION', 0)

cashflow = sell + redeem + merge - buy - split
print(f"Cash flow: {cashflow:.2f}")
print(f"Cash flow + rewards: {cashflow + reward:.2f}")
print(f"Gap from official: {OFFICIAL_PNL - cashflow - reward:.2f}")

# Now: CONVERSION analysis
# Conversions seem related to multi-outcome markets (neg risk)
# A conversion might be: buy all outcomes for $1 each, then sell the ones you don't want
# Or: convert USDC into a full set of outcome tokens
# If conversions are BUYING tokens (spending USDC), they should be a cost
# But we might already be counting the individual share buys as trades

# Check: do conversion markets overlap with trade markets?
c.execute("""
    SELECT DISTINCT market_id FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='CONVERSION'
""", (WALLET_ID,))
conv_markets = set(r[0] for r in c.fetchall())

c.execute("""
    SELECT DISTINCT market_id FROM wallet_analysis_trade WHERE wallet_id=?
""", (WALLET_ID,))
trade_markets = set(r[0] for r in c.fetchall())

overlap = conv_markets & trade_markets
print(f"\nConversion markets: {len(conv_markets)}")
print(f"Trade markets: {len(trade_markets)}")
print(f"Overlap: {len(overlap)}")
print(f"Conversion-only markets: {len(conv_markets - trade_markets)}")

# For overlapping markets, check if conversion USDC matches the buy trades
# Sample one conversion market
if overlap:
    sample_mid = list(overlap)[0]
    c.execute("SELECT title FROM wallet_analysis_market WHERE id=?", (sample_mid,))
    title = c.fetchone()[0]
    print(f"\nSample overlapping market: {title}")
    
    c.execute("""
        SELECT side, SUM(total_value), SUM(size), COUNT(*) 
        FROM wallet_analysis_trade WHERE wallet_id=? AND market_id=? GROUP BY side
    """, (WALLET_ID, sample_mid))
    for r in c.fetchall():
        print(f"  Trades {r[0]}: total_value={r[1]:.4f}, size={r[2]:.4f}, count={r[3]}")
    
    c.execute("""
        SELECT activity_type, SUM(usdc_size), SUM(size), COUNT(*)
        FROM wallet_analysis_activity WHERE wallet_id=? AND market_id=? GROUP BY activity_type
    """, (WALLET_ID, sample_mid))
    for r in c.fetchall():
        print(f"  Activity {r[0]}: usdc={r[1]:.4f}, size={r[2]:.4f}, count={r[3]}")

# Check: what if conversions represent USDC that's both spent AND received?
# i.e., conversion = split (buy all outcomes) + immediate sell of unwanted
# In that case, the buy cost is in the trades, and the conversion is double-counting

# Let's check: total cash flow WITHOUT splits and WITHOUT conversions
# If splits and conversions cancel out in the trade data...
cf_no_split = sell + redeem + merge - buy
print(f"\nCash flow without splits: {cf_no_split:.2f}")
print(f"Gap: {OFFICIAL_PNL - cf_no_split - reward:.2f}")

# What if we treat conversions like splits?
cf_with_conv = sell + redeem + merge - buy - split - conversion
print(f"\nCash flow with conv as cost: {cf_with_conv:.2f}")
print(f"Gap: {OFFICIAL_PNL - cf_with_conv - reward:.2f}")

# Key question: In the TRADE data, do split/conversion markets have corresponding BUY trades?
# If so, we're double-counting by subtracting splits
c.execute("""
    SELECT DISTINCT market_id FROM wallet_analysis_activity 
    WHERE wallet_id=? AND activity_type='SPLIT'
""", (WALLET_ID,))
split_markets = set(r[0] for r in c.fetchall())

split_trade_overlap = split_markets & trade_markets
print(f"\nSplit markets: {len(split_markets)}")
print(f"Split markets that also have trades: {len(split_trade_overlap)}")

# For splits: the USDC is spent to create tokens, which then appear as shares
# The trade BUY entries for these shares should NOT include the split cost
# because the shares came from splitting, not from buying on the book

# Let me check a split market
if split_trade_overlap:
    sample_split = list(split_trade_overlap)[0]
    c.execute("SELECT title FROM wallet_analysis_market WHERE id=?", (sample_split,))
    title = c.fetchone()[0]
    print(f"\nSample split market: {title}")
    
    c.execute("""
        SELECT side, SUM(total_value), SUM(size), COUNT(*)
        FROM wallet_analysis_trade WHERE wallet_id=? AND market_id=? GROUP BY side
    """, (WALLET_ID, sample_split))
    for r in c.fetchall():
        print(f"  Trades {r[0]}: total_value={r[1]:.4f}, size={r[2]:.4f}, count={r[3]}")
    
    c.execute("""
        SELECT activity_type, SUM(usdc_size), SUM(size), COUNT(*)
        FROM wallet_analysis_activity WHERE wallet_id=? AND market_id=? GROUP BY activity_type
    """, (WALLET_ID, sample_split))
    for r in c.fetchall():
        print(f"  Activity {r[0]}: usdc={r[1]:.4f}, size={r[2]:.4f}, count={r[3]}")

# Open positions (bought - sold > 0) that are NOT resolved
print("\n=== OPEN UNRESOLVED POSITIONS ===")
c.execute("""
    SELECT t.asset, t.outcome, 
           SUM(CASE WHEN t.side='BUY' THEN t.size ELSE 0 END) as bought,
           SUM(CASE WHEN t.side='SELL' THEN t.size ELSE 0 END) as sold,
           SUM(CASE WHEN t.side='BUY' THEN t.total_value ELSE 0 END) as buy_cost,
           m.resolved, m.winning_outcome, m.title
    FROM wallet_analysis_trade t
    JOIN wallet_analysis_market m ON t.market_id = m.id
    WHERE t.wallet_id = ?
    GROUP BY t.asset
    HAVING bought - sold > 0.01 AND m.resolved = 0
""", (WALLET_ID,))
open_unresolved = c.fetchall()
total_open_cost = 0
for r in open_unresolved:
    remaining = r[2] - r[3]
    cost = r[4] * (remaining / r[2]) if r[2] > 0 else 0  # approximate
    total_open_cost += cost
    if remaining > 1:
        print(f"  {r[7][:60]}: {remaining:.2f} '{r[1]}' shares, ~cost ${cost:.2f}")
print(f"Total open unresolved cost: ${total_open_cost:.2f}")

conn.close()
