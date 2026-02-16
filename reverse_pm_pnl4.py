"""Part 4: Analyze TRADE activities and look at frontend API."""
import urllib.request
import json
from datetime import datetime, timedelta, timezone

ADDR = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

# Fetch activity again, look at TRADE entries
all_activity = []
offset = 0
while True:
    url = f"https://data-api.polymarket.com/activity?user={ADDR}&limit=100&offset={offset}"
    try:
        data = fetch(url)
    except:
        break
    if not data:
        break
    all_activity.extend(data)
    if len(data) < 100:
        break
    offset += 100

# Show sample TRADE
trades = [a for a in all_activity if a["type"] == "TRADE"]
redeems = [a for a in all_activity if a["type"] == "REDEEM"]
merges = [a for a in all_activity if a["type"] == "MERGE"]

print(f"Total: {len(all_activity)}, TRADE: {len(trades)}, REDEEM: {len(redeems)}, MERGE: {len(merges)}")
print(f"\nSample TRADE: {json.dumps(trades[0], indent=2)}")
print(f"\nSample REDEEM: {json.dumps(redeems[0], indent=2)}")

# For TRADE: side=BUY means spending USDC, side=SELL means receiving USDC
# usdcSize = amount of USDC involved
buys = [a for a in trades if a.get("side") == "BUY"]
sells = [a for a in trades if a.get("side") == "SELL"]
print(f"\nTRADE BUY: {len(buys)}, TRADE SELL: {len(sells)}")

buy_usdc = sum(float(a.get("usdcSize", 0)) for a in buys)
sell_usdc = sum(float(a.get("usdcSize", 0)) for a in sells)
redeem_usdc = sum(float(a.get("usdcSize", 0)) for a in redeems)
merge_usdc = sum(float(a.get("usdcSize", 0)) for a in merges)

print(f"\nBuy USDC: ${buy_usdc:.2f}")
print(f"Sell USDC: ${sell_usdc:.2f}")
print(f"Redeem USDC: ${redeem_usdc:.2f}")
print(f"Merge USDC: ${merge_usdc:.2f}")
print(f"\nPnL = (sell + redeem + merge) - buy = ${sell_usdc + redeem_usdc + merge_usdc - buy_usdc:.2f}")
print(f"PnL = (sell + redeem) - buy = ${sell_usdc + redeem_usdc - buy_usdc:.2f}")

# Time filter
one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
one_month_ts = int(one_month_ago.timestamp())

recent = [a for a in all_activity if a["timestamp"] >= one_month_ts]
r_buys = [a for a in recent if a["type"] == "TRADE" and a.get("side") == "BUY"]
r_sells = [a for a in recent if a["type"] == "TRADE" and a.get("side") == "SELL"]
r_redeems = [a for a in recent if a["type"] == "REDEEM"]
r_merges = [a for a in recent if a["type"] == "MERGE"]

rb = sum(float(a.get("usdcSize", 0)) for a in r_buys)
rs = sum(float(a.get("usdcSize", 0)) for a in r_sells)
rr = sum(float(a.get("usdcSize", 0)) for a in r_redeems)
rm = sum(float(a.get("usdcSize", 0)) for a in r_merges)

print(f"\n=== LAST 30 DAYS ===")
print(f"Buy: ${rb:.2f} ({len(r_buys)}), Sell: ${rs:.2f} ({len(r_sells)}), Redeem: ${rr:.2f} ({len(r_redeems)}), Merge: ${rm:.2f} ({len(r_merges)})")
print(f"PnL = ${rs + rr + rm - rb:.2f}")

print(f"\nTargets: 1M=$1,282.17  ALL=$20,172.75")

# Try fetching older activity with before param
print(f"\n=== TRYING TO GET OLDER ACTIVITY ===")
oldest_ts = min(a["timestamp"] for a in all_activity)
print(f"Oldest so far: {datetime.fromtimestamp(oldest_ts, tz=timezone.utc)}")

# Try with before= parameter
try:
    url = f"https://data-api.polymarket.com/activity?user={ADDR}&limit=100&before={oldest_ts}"
    older = fetch(url)
    print(f"With before={oldest_ts}: {len(older)} results")
    if older:
        oldest2 = min(a["timestamp"] for a in older)
        print(f"  Oldest: {datetime.fromtimestamp(oldest2, tz=timezone.utc)}")
except Exception as e:
    print(f"Error: {e}")

# Try with end= parameter
try:
    url = f"https://data-api.polymarket.com/activity?user={ADDR}&limit=100&end={oldest_ts}"
    older = fetch(url)
    print(f"With end={oldest_ts}: {len(older)} results")
except Exception as e:
    print(f"Error with end=: {e}")

# Try the gamma API
print(f"\n=== TRYING GAMMA API ===")
for ep in [
    f"https://gamma-api.polymarket.com/users/{ADDR}",
    f"https://gamma-api.polymarket.com/profiles/{ADDR}",
    f"https://gamma-api.polymarket.com/query?user={ADDR}",
]:
    try:
        data = fetch(ep)
        print(f"OK {ep}: {json.dumps(data)[:500]}")
    except urllib.error.HTTPError as e:
        print(f"{e.code} {ep}")
    except Exception as e:
        print(f"ERR {ep}")

# Check if there's a GraphQL endpoint
print("\n=== Positions with sizeThreshold=0 (all) ===")
positions = fetch(f"https://data-api.polymarket.com/positions?user={ADDR}&sizeThreshold=0&limit=500")
print(f"Count: {len(positions)}")

# For each position, compute: pnl = realizedPnl + cashPnl
all_pnl = sum(float(p.get("realizedPnl", 0)) + float(p.get("cashPnl", 0)) for p in positions)
print(f"Sum(realizedPnl + cashPnl): ${all_pnl:.2f}")

# What about: totalBought vs value received?
for p in positions[:3]:
    tb = float(p.get("totalBought", 0))
    iv = float(p.get("initialValue", 0))
    cv = float(p.get("currentValue", 0))
    rp = float(p.get("realizedPnl", 0))
    cp = float(p.get("cashPnl", 0))
    print(f"\n  {p['title'][:60]}")
    print(f"  size={p['size']}, avgPrice={p['avgPrice']}, totalBought={tb}")
    print(f"  initialValue={iv}, currentValue={cv}")
    print(f"  realizedPnl={rp}, cashPnl={cp}")
    print(f"  PnL = realized+cash = {rp+cp:.4f}")
    print(f"  Check: cashPnl = currentValue - initialValue? {cv - iv:.4f} vs {cp:.4f}")
    print(f"  Check: size*avgPrice = initialValue? {float(p['size'])*float(p['avgPrice']):.4f} vs {iv:.4f}")
