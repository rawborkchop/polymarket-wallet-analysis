"""Part 6: Fetch the actual endpoints Polymarket frontend uses."""
import urllib.request
import json

ADDR = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

# Key endpoints from frontend
print("=== USER STATS (v1) ===")
data = fetch(f"https://data-api.polymarket.com/v1/user-stats?proxyAddress={ADDR}")
print(json.dumps(data, indent=2))

print("\n=== LEADERBOARD ===")
data = fetch(f"https://data-api.polymarket.com/v1/leaderboard?timePeriod=all&orderBy=VOL&limit=1&offset=0&category=overall&user={ADDR}")
print(json.dumps(data, indent=2)[:2000])

print("\n=== TRADED ===")
data = fetch(f"https://data-api.polymarket.com/traded?user={ADDR}")
print(json.dumps(data, indent=2)[:2000])

# Try different timePeriods for leaderboard
for period in ["1m", "1w", "1d", "all", "month", "week"]:
    try:
        data = fetch(f"https://data-api.polymarket.com/v1/leaderboard?timePeriod={period}&orderBy=PNL&limit=1&offset=0&category=overall&user={ADDR}")
        print(f"\nLeaderboard {period}:")
        print(json.dumps(data, indent=2)[:500])
    except Exception as e:
        print(f"\nLeaderboard {period}: {e}")
