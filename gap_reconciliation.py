"""Reconciliation script: fetch Polymarket positions API and compare with our DB."""
import urllib.request, json, sqlite3

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return json.loads(urllib.request.urlopen(req).read())

WALLET = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
WALLET_ID = 7
OFFICIAL_PNL = 20172.77

# 1. Fetch all positions from Polymarket API
all_positions = []
offset = 0
while True:
    url = f'https://data-api.polymarket.com/v1/positions?user={WALLET}&sizeThreshold=-1&limit=500&offset={offset}'
    data = fetch_json(url)
    if not data:
        break
    all_positions.extend(data)
    if len(data) < 500:
        break
    offset += 500

total_cash_pnl = sum(p['cashPnl'] for p in all_positions)
total_realized = sum(p.get('realizedPnl', 0) for p in all_positions)
total_initial = sum(p['initialValue'] for p in all_positions)
total_current = sum(p['currentValue'] for p in all_positions)
total_bought = sum(p['totalBought'] for p in all_positions)

print(f"Positions from API: {len(all_positions)}")
print(f"Sum cashPnl:       {total_cash_pnl:12.2f}")
print(f"Sum realizedPnl:   {total_realized:12.2f}")
print(f"Sum initialValue:  {total_initial:12.2f}")
print(f"Sum currentValue:  {total_current:12.2f}")
print(f"Sum totalBought:   {total_bought:12.2f} (shares)")
print(f"cashPnl+current:   {total_cash_pnl + total_current:12.2f}")
print(f"Official PnL:      {OFFICIAL_PNL:12.2f}")
print(f"Gap (official-cashPnl): {OFFICIAL_PNL - total_cash_pnl:12.2f}")

# Open positions
open_pos = [p for p in all_positions if p['currentValue'] > 0]
print(f"\nOpen positions: {len(open_pos)}, total currentValue: {sum(p['currentValue'] for p in open_pos):.2f}")

# 2. Compare with our DB
print("\n" + "="*70)
print("DB COMPARISON")
print("="*70)

conn = sqlite3.connect("db.sqlite3")
c = conn.cursor()

c.execute("SELECT side, SUM(total_value), SUM(size) FROM wallet_analysis_trade WHERE wallet_id=? GROUP BY side", (WALLET_ID,))
trades = {r[0]: {'value': r[1], 'size': r[2]} for r in c.fetchall()}

c.execute("SELECT activity_type, SUM(usdc_size), COUNT(*) FROM wallet_analysis_activity WHERE wallet_id=? GROUP BY activity_type", (WALLET_ID,))
acts = {r[0]: {'usdc': r[1] or 0, 'count': r[2]} for r in c.fetchall()}

buy = trades['BUY']['value']
sell = trades['SELL']['value']
redeem = acts.get('REDEEM', {}).get('usdc', 0)
merge = acts.get('MERGE', {}).get('usdc', 0)
split = acts.get('SPLIT', {}).get('usdc', 0)
reward = acts.get('REWARD', {}).get('usdc', 0)
conversion = acts.get('CONVERSION', {}).get('usdc', 0)

v2 = sell + redeem + merge - buy - split
v3 = v2 + reward

print(f"V2 (sell+redeem+merge-buy-split):  {v2:.2f}")
print(f"V3 (V2+reward):                    {v3:.2f}")
print(f"Reward:                            {reward:.2f}")
print(f"Conversion:                        {conversion:.2f}")

# 3. Key question: does sum(cashPnl) from API == official PnL?
print(f"\n--- KEY FINDING ---")
print(f"API sum(cashPnl):  {total_cash_pnl:.2f}")
print(f"Leaderboard PnL:   {OFFICIAL_PNL:.2f}")
print(f"Difference:        {OFFICIAL_PNL - total_cash_pnl:.2f}")
print(f"(If ~0, then PnL = sum of per-position cashPnl)")

# 4. What is cashPnl? For each position: cashPnl = realized_sells - initialValue of remaining
# cashPnl = total_sold_revenue + total_redeemed - totalBought_cost
# Let's verify with a sample
print(f"\n--- SAMPLE POSITIONS ---")
for p in all_positions[:5]:
    print(f"  {p['title'][:50]}")
    print(f"    cashPnl={p['cashPnl']:.4f}  realizedPnl={p.get('realizedPnl',0):.4f}")
    print(f"    initialValue={p['initialValue']:.4f}  currentValue={p['currentValue']:.4f}")
    print(f"    size={p['size']:.4f}  avgPrice={p['avgPrice']:.4f}  totalBought={p['totalBought']:.4f}")

# 5. What's the unrealized PnL from open positions?
unrealized = sum(p['currentValue'] - p['initialValue'] for p in all_positions if p['currentValue'] > 0)
print(f"\nUnrealized PnL (open positions): {unrealized:.2f}")
print(f"V3 + unrealized: {v3 + unrealized:.2f}")

# 6. Check: does PM PnL = cashPnl + unrealized?
# If cashPnl already includes unrealized losses on held positions, then PnL = sum(cashPnl) + sum(currentValue)
print(f"\nsum(cashPnl) + sum(currentValue) = {total_cash_pnl + total_current:.2f}")
print(f"This vs official: {OFFICIAL_PNL - total_cash_pnl - total_current:.2f}")

conn.close()
