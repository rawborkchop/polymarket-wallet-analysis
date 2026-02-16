"""Part 3: Compute PnL from activity data with error handling."""
import urllib.request
import json
from datetime import datetime, timedelta, timezone
from collections import Counter

ADDR = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

# Fetch all activity with error handling
all_activity = []
offset = 0
while True:
    url = f"https://data-api.polymarket.com/activity?user={ADDR}&limit=100&offset={offset}"
    try:
        data = fetch(url)
    except Exception as e:
        print(f"Stopped at offset {offset}: {e}")
        break
    if not data:
        break
    all_activity.extend(data)
    if len(data) < 100:
        break
    offset += 100

print(f"Total activities: {len(all_activity)}")
types = Counter(a["type"] for a in all_activity)
print(f"Types: {dict(types)}")

# Time ranges
one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
one_month_ts = int(one_month_ago.timestamp())

# Get earliest/latest timestamps
timestamps = [a["timestamp"] for a in all_activity]
print(f"Activity range: {datetime.fromtimestamp(min(timestamps), tz=timezone.utc)} to {datetime.fromtimestamp(max(timestamps), tz=timezone.utc)}")

def compute_pnl(activities, label):
    redeems = sum(float(a.get("usdcSize", 0)) for a in activities if a["type"] == "REDEEM")
    buys_usdc = sum(float(a.get("usdcSize", 0)) for a in activities if a["type"] == "BUY")
    sells_usdc = sum(float(a.get("usdcSize", 0)) for a in activities if a["type"] == "SELL")
    # PnL = money out - money in = (redeems + sells) - buys
    pnl = redeems + sells_usdc - buys_usdc
    print(f"\n{label}:")
    print(f"  BUY total: ${buys_usdc:.2f} ({sum(1 for a in activities if a['type']=='BUY')} txs)")
    print(f"  SELL total: ${sells_usdc:.2f} ({sum(1 for a in activities if a['type']=='SELL')} txs)")
    print(f"  REDEEM total: ${redeems:.2f} ({sum(1 for a in activities if a['type']=='REDEEM')} txs)")
    print(f"  PnL (redeem+sell-buy): ${pnl:.2f}")
    # Also try: for buys, cost = size * price; for redeems, gain = usdcSize
    # PnL alternative: redeem - (buy_size * buy_price)
    buy_cost = sum(float(a.get("size", 0)) * float(a.get("price", 0)) for a in activities if a["type"] == "BUY")
    print(f"  Buy cost (size*price): ${buy_cost:.2f}")
    print(f"  PnL alt (redeem-buy_cost): ${redeems - buy_cost:.2f}")
    return pnl

compute_pnl(all_activity, "ALL TIME")
recent = [a for a in all_activity if a["timestamp"] >= one_month_ts]
compute_pnl(recent, f"LAST 30 DAYS (since {one_month_ago.strftime('%Y-%m-%d')})")

print(f"\nTargets: 1M=$1,282.17  ALL=$20,172.75")

# Also check: maybe positions API with sizeThreshold=-1 returns more?
positions = fetch(f"https://data-api.polymarket.com/positions?user={ADDR}&sizeThreshold=-1&limit=500")
print(f"\nPositions with sizeThreshold=-1: {len(positions)}")

# Check for size=0 positions (fully closed/redeemed)
closed = [p for p in positions if float(p.get("size", 0)) == 0]
print(f"Closed positions (size=0): {len(closed)}")

# Sum all PnL fields across ALL positions including closed
total_realized = sum(float(p.get("realizedPnl", 0)) for p in positions)
total_cash = sum(float(p.get("cashPnl", 0)) for p in positions)
total_cur = sum(float(p.get("curPnl", 0)) for p in positions if p.get("curPnl"))
total_initial = sum(float(p.get("initialValue", 0)) for p in positions)
total_current = sum(float(p.get("currentValue", 0)) for p in positions)
total_bought = sum(float(p.get("totalBought", 0)) for p in positions)

print(f"\nPositions sums:")
print(f"  realizedPnl: ${total_realized:.2f}")
print(f"  cashPnl: ${total_cash:.2f}")
print(f"  initialValue: ${total_initial:.2f}")
print(f"  currentValue: ${total_current:.2f}")
print(f"  totalBought: ${total_bought:.2f}")
print(f"  realized + cash: ${total_realized + total_cash:.2f}")
print(f"  realized + cash + currentValue: ${total_realized + total_cash + total_current:.2f}")

# Try the profile/leaderboard type endpoints
for ep in [
    f"https://data-api.polymarket.com/leaderboard/rank?user={ADDR}",
    f"https://data-api.polymarket.com/leaderboard/profit?user={ADDR}",
    f"https://data-api.polymarket.com/profile/{ADDR}",
    f"https://data-api.polymarket.com/users/{ADDR}",
]:
    try:
        data = fetch(ep)
        print(f"\nOK {ep}")
        print(f"   {json.dumps(data)[:500]}")
    except urllib.error.HTTPError as e:
        print(f"\n{e.code} {ep}")
    except Exception as e:
        print(f"\nERR {ep}")
