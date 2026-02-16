"""Part 5: Try to find the exact PnL API endpoint from Polymarket frontend."""
import urllib.request
import json

ADDR = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

# Try various profile endpoints that might return PnL summary
endpoints = [
    # Profile endpoints
    f"https://polymarket.com/api/profile/{ADDR}",
    f"https://polymarket.com/api/users/{ADDR}",
    # data-api with different paths
    f"https://data-api.polymarket.com/value?user={ADDR}",
    f"https://data-api.polymarket.com/summary?user={ADDR}",
    f"https://data-api.polymarket.com/performance?user={ADDR}",
    # Try with address as path
    f"https://data-api.polymarket.com/positions/summary?user={ADDR}",
    f"https://data-api.polymarket.com/positions/pnl?user={ADDR}",
    # Rewards/leaderboard
    f"https://data-api.polymarket.com/rewards?user={ADDR}",
    # Volume
    f"https://data-api.polymarket.com/volume?user={ADDR}",
    # History
    f"https://data-api.polymarket.com/history?user={ADDR}",
    # Try the profilePnl pattern
    f"https://data-api.polymarket.com/profilePnl?user={ADDR}",
    f"https://data-api.polymarket.com/profile-pnl?user={ADDR}",
    # Try timeseries
    f"https://data-api.polymarket.com/timeseries?user={ADDR}",
    f"https://data-api.polymarket.com/portfolio/timeseries?user={ADDR}",
    f"https://data-api.polymarket.com/pnl-timeseries?user={ADDR}",
    f"https://data-api.polymarket.com/pnlTimeseries?user={ADDR}",
]

for ep in endpoints:
    try:
        data = fetch(ep)
        print(f"OK {ep}")
        print(f"   {json.dumps(data)[:500]}")
    except urllib.error.HTTPError as e:
        print(f"{e.code} {ep}")
    except Exception as e:
        print(f"ERR {ep} -> {str(e)[:80]}")
