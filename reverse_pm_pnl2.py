"""Part 2: Try more API endpoints to find PnL source."""
import urllib.request
import json

ADDR = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

endpoints = [
    f"https://data-api.polymarket.com/pnl?user={ADDR}",
    f"https://data-api.polymarket.com/profit?user={ADDR}",
    f"https://data-api.polymarket.com/profits?user={ADDR}",
    f"https://data-api.polymarket.com/profits?user={ADDR}&window=1m",
    f"https://data-api.polymarket.com/earnings?user={ADDR}",
    f"https://data-api.polymarket.com/portfolio?user={ADDR}",
    f"https://data-api.polymarket.com/pnl/timeseries?user={ADDR}",
    f"https://profit-api.polymarket.com/profits?user={ADDR}",
    f"https://data-api.polymarket.com/rank?user={ADDR}",
    f"https://data-api.polymarket.com/leaderboard?user={ADDR}",
    f"https://data-api.polymarket.com/users?user={ADDR}",
    f"https://data-api.polymarket.com/user?user={ADDR}",
    f"https://data-api.polymarket.com/profile?user={ADDR}",
    f"https://data-api.polymarket.com/stats?user={ADDR}",
    f"https://data-api.polymarket.com/balance?user={ADDR}",
    f"https://data-api.polymarket.com/wallets?user={ADDR}",
    f"https://data-api.polymarket.com/positions?user={ADDR}&sizeThreshold=-1",
    f"https://data-api.polymarket.com/positions?user={ADDR}&includeHistory=true",
    f"https://data-api.polymarket.com/positions?user={ADDR}&closed=true",
]

for ep in endpoints:
    try:
        data = fetch(ep)
        resp = json.dumps(data, indent=2)[:600]
        print(f"OK {ep}")
        print(f"   {resp}")
    except urllib.error.HTTPError as e:
        print(f"{e.code} {ep}")
    except Exception as e:
        print(f"ERR {ep} -> {str(e)[:100]}")
    print()

# Also try fetching ALL activity (not just 100) to sum up PnL
print("=== FETCHING ALL ACTIVITY ===")
all_activity = []
offset = 0
while True:
    url = f"https://data-api.polymarket.com/activity?user={ADDR}&limit=100&offset={offset}"
    data = fetch(url)
    if not data:
        break
    all_activity.extend(data)
    if len(data) < 100:
        break
    offset += 100
    print(f"  fetched {len(all_activity)} activities...")

print(f"Total activities: {len(all_activity)}")

# Analyze activity types
from collections import Counter
types = Counter(a["type"] for a in all_activity)
print(f"Activity types: {dict(types)}")

# For REDEEM activities, sum usdcSize (this is money coming back)
redeems = [a for a in all_activity if a["type"] == "REDEEM"]
buys = [a for a in all_activity if a["type"] == "BUY"]
sells = [a for a in all_activity if a["type"] == "SELL"]

redeem_total = sum(float(a.get("usdcSize", 0)) for a in redeems)
buy_total = sum(float(a.get("usdcSize", 0)) for a in buys)
sell_total = sum(float(a.get("usdcSize", 0)) for a in sells)

print(f"\nREDEEM total: ${redeem_total:.2f} ({len(redeems)} txs)")
print(f"BUY total: ${buy_total:.2f} ({len(buys)} txs)")
print(f"SELL total: ${sell_total:.2f} ({len(sells)} txs)")
print(f"Net (redeem+sell-buy): ${redeem_total + sell_total - buy_total:.2f}")

# Time-based: last 30 days
from datetime import datetime, timedelta, timezone
one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
one_month_ts = int(one_month_ago.timestamp())

recent = [a for a in all_activity if a.get("timestamp", 0) >= one_month_ts]
recent_redeems = [a for a in recent if a["type"] == "REDEEM"]
recent_buys = [a for a in recent if a["type"] == "BUY"]
recent_sells = [a for a in recent if a["type"] == "SELL"]

r_redeem = sum(float(a.get("usdcSize", 0)) for a in recent_redeems)
r_buy = sum(float(a.get("usdcSize", 0)) for a in recent_buys)
r_sell = sum(float(a.get("usdcSize", 0)) for a in recent_sells)

print(f"\n=== LAST 30 DAYS ===")
print(f"REDEEM: ${r_redeem:.2f} ({len(recent_redeems)} txs)")
print(f"BUY: ${r_buy:.2f} ({len(recent_buys)} txs)")  
print(f"SELL: ${r_sell:.2f} ({len(recent_sells)} txs)")
print(f"Net (redeem+sell-buy): ${r_redeem + r_sell - r_buy:.2f}")

# Compute PnL per trade: for each buy, pnl = size * (redemption_price - avg_price)
# But we need to match buys to redemptions...
# Simpler: PnL = total_received - total_spent
# total_received = redeems + sells
# total_spent = buys
print(f"\nTarget 1M: $1,282.17")
print(f"Target ALL: $20,172.75")
