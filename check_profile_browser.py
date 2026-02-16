"""Try various API endpoints to find profile PnL and linked wallets."""
import requests
import json

ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
s = requests.Session()
s.headers.update({"Accept": "application/json", "User-Agent": "Mozilla/5.0"})

# Try the activity endpoint to check for different proxy wallets
endpoints = [
    f"https://data-api.polymarket.com/activity?address={ADDRESS}&limit=5",
    f"https://data-api.polymarket.com/activity?user={ADDRESS}&limit=5", 
    f"https://gamma-api.polymarket.com/activity?address={ADDRESS}&limit=5",
    f"https://data-api.polymarket.com/wallets?address={ADDRESS}",
    f"https://data-api.polymarket.com/pnl?address={ADDRESS}",
    f"https://data-api.polymarket.com/rewards?address={ADDRESS}",
]

for url in endpoints:
    try:
        resp = s.get(url, timeout=10)
        print(f"\nGET {url}")
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print(json.dumps(resp.json(), indent=2)[:600])
    except Exception as ex:
        print(f"Error: {ex}")

# Check if positions have different proxyWallet values (multiple wallets)
print("\n\n=== Checking proxyWallet in positions ===")
resp = s.get(f"https://data-api.polymarket.com/positions?user={ADDRESS}&limit=500&sizeThreshold=0", timeout=30)
if resp.status_code == 200:
    positions = resp.json()
    wallets = set(p.get('proxyWallet', '') for p in positions)
    print(f"Unique proxyWallet values: {wallets}")

# Try the activity/history endpoint
print("\n=== Activity history ===")
resp = s.get(f"https://data-api.polymarket.com/activity?user={ADDRESS}&limit=3&offset=0", timeout=10)
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    print(json.dumps(resp.json(), indent=2)[:800])
