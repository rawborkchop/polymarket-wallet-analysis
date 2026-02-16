"""
Calculate PnL using Polymarket's avg-cost-basis methodology.
For each asset, track: shares held, avg cost per share.
Realized PnL = shares_sold * (sell_price - avg_cost).
For redeems: sell_price = 1.0 for winners, 0.0 for losers.
"""
import sqlite3
from collections import defaultdict
from decimal import Decimal

WALLET_ID = 7
OFFICIAL_PNL = 20172.77

conn = sqlite3.connect('db.sqlite3')
conn.row_factory = sqlite3.Row

# Get all trades ordered by time
trades = conn.execute("""
    SELECT t.asset, t.side, t.price, t.size, t.total_value, t.timestamp, t.outcome,
           m.title, m.winning_outcome, m.resolved
    FROM wallet_analysis_trade t
    LEFT JOIN wallet_analysis_market m ON t.market_id = m.id
    WHERE t.wallet_id = ?
    ORDER BY t.timestamp ASC, t.id ASC
""", (WALLET_ID,)).fetchall()

# Get all activities (redeems, merges, splits, conversions)
activities = conn.execute("""
    SELECT a.activity_type, a.asset, a.outcome, a.size, a.usdc_size, a.timestamp,
           m.title, m.winning_outcome, m.resolved, a.market_id
    FROM wallet_analysis_activity a
    LEFT JOIN wallet_analysis_market m ON a.market_id = m.id
    WHERE a.wallet_id = ?
    ORDER BY a.timestamp ASC, a.id ASC
""", (WALLET_ID,)).fetchall()

print(f"Loaded {len(trades)} trades, {len(activities)} activities")

# Build combined event stream
events = []
for t in trades:
    events.append({
        'type': 'TRADE',
        'timestamp': t['timestamp'],
        'asset': t['asset'],
        'side': t['side'],
        'price': float(t['price']),
        'size': float(t['size']),
        'total_value': float(t['total_value']),
        'outcome': t['outcome'],
        'title': t['title'],
        'winning_outcome': t['winning_outcome'],
        'resolved': t['resolved'],
    })

for a in activities:
    events.append({
        'type': a['activity_type'],
        'timestamp': a['timestamp'],
        'asset': a['asset'],
        'outcome': a['outcome'],
        'size': float(a['size']),
        'usdc_size': float(a['usdc_size']),
        'title': a['title'],
        'winning_outcome': a['winning_outcome'],
        'resolved': a['resolved'],
        'market_id': a['market_id'],
    })

events.sort(key=lambda e: e['timestamp'])

# Track positions per asset
class Position:
    def __init__(self):
        self.shares = 0.0
        self.avg_cost = 0.0
        self.total_cost = 0.0
        self.realized_pnl = 0.0

positions = defaultdict(Position)
total_realized_pnl = 0.0
total_rewards = 0.0
conversion_pnl = 0.0  # splits/merges/conversions

for e in events:
    if e['type'] == 'TRADE':
        asset = e['asset']
        pos = positions[asset]
        
        if e['side'] == 'BUY':
            # Update avg cost
            new_cost = e['total_value']
            new_shares = e['size']
            pos.total_cost += new_cost
            pos.shares += new_shares
            if pos.shares > 0:
                pos.avg_cost = pos.total_cost / pos.shares
        
        elif e['side'] == 'SELL':
            sell_price = e['price']
            shares_sold = e['size']
            pnl = shares_sold * (sell_price - pos.avg_cost)
            pos.realized_pnl += pnl
            total_realized_pnl += pnl
            pos.shares -= shares_sold
            pos.total_cost = pos.avg_cost * max(pos.shares, 0)
            if pos.shares < 0.001:
                pos.shares = 0
                pos.total_cost = 0
                pos.avg_cost = 0
    
    elif e['type'] == 'REDEEM':
        # Need to find which assets were redeemed for this market
        # Redeems close out all shares in a market at $1 (winner) or $0 (loser)
        # But we don't have the asset ID in the activity... 
        # We need to find positions linked to this market
        pass  # Handle below
    
    elif e['type'] == 'REWARD':
        total_rewards += e['usdc_size']
    
    elif e['type'] in ('SPLIT', 'MERGE', 'CONVERSION'):
        # These are USDC in/out but don't directly create shares in our trade data
        # Splits: pay USDC, get shares (but shares appear as trades?)
        # Let's skip for now and see
        pass

# Now handle redeems - find all assets per market and close them
# Get market -> assets mapping from trades
market_assets = defaultdict(set)
for t in trades:
    # We need market_id but trades don't have it directly accessible here
    pass

# Alternative: use the DB to get market_id -> asset mapping
asset_market = {}
for row in conn.execute("""
    SELECT DISTINCT asset, market_id FROM wallet_analysis_trade WHERE wallet_id=?
""", (WALLET_ID,)):
    asset_market[row['asset']] = row['market_id']

market_to_assets = defaultdict(set)
for asset, mid in asset_market.items():
    market_to_assets[mid].add(asset)

# Get market winning outcomes
market_info = {}
for row in conn.execute("SELECT id, winning_outcome, resolved FROM wallet_analysis_market"):
    market_info[row['id']] = {'winning_outcome': row['winning_outcome'], 'resolved': row['resolved']}

# Get trade outcome for each asset
asset_outcome = {}
for row in conn.execute("""
    SELECT DISTINCT asset, outcome FROM wallet_analysis_trade WHERE wallet_id=?
""", (WALLET_ID,)):
    asset_outcome[row['asset']] = row['outcome']

# Now process redeems
redeem_pnl = 0.0
for a in activities:
    if a['activity_type'] != 'REDEEM':
        continue
    mid = a['market_id']
    info = market_info.get(mid, {})
    winning = info.get('winning_outcome', '')
    
    # Close all positions in this market
    for asset in market_to_assets.get(mid, set()):
        pos = positions[asset]
        if pos.shares < 0.001:
            continue
        outcome = asset_outcome.get(asset, '')
        if outcome == winning:
            redeem_price = 1.0
        else:
            redeem_price = 0.0
        
        pnl = pos.shares * (redeem_price - pos.avg_cost)
        pos.realized_pnl += pnl
        redeem_pnl += pnl
        total_realized_pnl += pnl
        pos.shares = 0
        pos.total_cost = 0
        pos.avg_cost = 0

# Open positions value
open_value = 0.0
open_count = 0
for asset, pos in positions.items():
    if pos.shares > 0.001:
        open_count += 1
        # unrealized = shares * (current_price - avg_cost), but we don't have current prices
        # Just note the cost basis
        open_value += pos.total_cost

print(f"\n=== AVG COST BASIS PnL ===")
print(f"Realized PnL from sells: {total_realized_pnl - redeem_pnl:.2f}")
print(f"Realized PnL from redeems: {redeem_pnl:.2f}")
print(f"Total realized PnL: {total_realized_pnl:.2f}")
print(f"Rewards: {total_rewards:.2f}")
print(f"Total (realized + rewards): {total_realized_pnl + total_rewards:.2f}")
print(f"Open positions: {open_count} with cost basis {open_value:.2f}")
print(f"Official PnL: {OFFICIAL_PNL}")
print(f"Gap: {OFFICIAL_PNL - total_realized_pnl - total_rewards:.2f}")

# Also compute simple cash flow for comparison
buy_total = sum(float(t['total_value']) for t in trades if t['side'] == 'BUY')
sell_total = sum(float(t['total_value']) for t in trades if t['side'] == 'SELL')
redeem_total = sum(float(a['usdc_size']) for a in activities if a['activity_type'] == 'REDEEM')
merge_total = sum(float(a['usdc_size']) for a in activities if a['activity_type'] == 'MERGE')
split_total = sum(float(a['usdc_size']) for a in activities if a['activity_type'] == 'SPLIT')
reward_total = sum(float(a['usdc_size']) for a in activities if a['activity_type'] == 'REWARD')
conversion_total = sum(float(a['usdc_size']) for a in activities if a['activity_type'] == 'CONVERSION')

cashflow = sell_total + redeem_total + merge_total - buy_total - split_total
print(f"\n=== CASH FLOW COMPARISON ===")
print(f"Buy: {buy_total:.2f}")
print(f"Sell: {sell_total:.2f}")  
print(f"Redeem: {redeem_total:.2f}")
print(f"Merge: {merge_total:.2f}")
print(f"Split: {split_total:.2f}")
print(f"Conversion: {conversion_total:.2f}")
print(f"Cash flow (sell+redeem+merge-buy-split): {cashflow:.2f}")
print(f"Cash flow + rewards: {cashflow + reward_total:.2f}")
print(f"Gap from official: {OFFICIAL_PNL - cashflow - reward_total:.2f}")

# Check: are conversions accounted for?
print(f"\n=== CONVERSION ANALYSIS ===")
print(f"Conversion USDC total: {conversion_total:.2f}")
print(f"If conversions are splits (cost): gap becomes {OFFICIAL_PNL - cashflow - reward_total + conversion_total:.2f}")
print(f"If conversions are ignored: gap is {OFFICIAL_PNL - cashflow - reward_total:.2f}")

# Check what happens if we include conversions as cost
cashflow_with_conv = sell_total + redeem_total + merge_total - buy_total - split_total - conversion_total
print(f"Cash flow with conversions as cost: {cashflow_with_conv:.2f}")
print(f"+ rewards: {cashflow_with_conv + reward_total:.2f}")
print(f"Gap: {OFFICIAL_PNL - cashflow_with_conv - reward_total:.2f}")

conn.close()
