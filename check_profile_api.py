"""Check various Polymarket API endpoints for profile/PnL data."""
import requests
import json

ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
s = requests.Session()
s.headers.update({"Accept": "application/json", "User-Agent": "Mozilla/5.0"})

# Try multiple API patterns
endpoints = [
    f"https://data-api.polymarket.com/leaderboard?window=all&limit=1&offset=0&id={ADDRESS}",
    f"https://data-api.polymarket.com/leaderboard?window=all&limit=5&name=1pixel",
    f"https://data-api.polymarket.com/profit?address={ADDRESS}&window=all",
    f"https://data-api.polymarket.com/profit?address={ADDRESS}",
    f"https://data-api.polymarket.com/positions?user={ADDRESS}&limit=5&offset=0&sortBy=pnl&status=closed",
    f"https://data-api.polymarket.com/positions?user={ADDRESS}&limit=5&offset=0&status=all",
    f"https://data-api.polymarket.com/positions?user={ADDRESS}&limit=5&offset=0&status=resolved",
]

for url in endpoints:
    try:
        resp = s.get(url, timeout=10)
        print(f"\n{'='*80}")
        print(f"GET {url}")
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            text = json.dumps(data, indent=2)
            print(text[:1000])
            if isinstance(data, list):
                print(f"  ... ({len(data)} items)")
    except Exception as ex:
        print(f"Error: {ex}")
