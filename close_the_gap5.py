"""Try to find the right API endpoint for Polymarket PnL data."""
import requests
import json

ADDRESS = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
headers = {"User-Agent": "Mozilla/5.0"}

# Known Polymarket API patterns
endpoints = [
    f"https://polymarket.com/api/profile/{ADDRESS}",
    f"https://polymarket.com/api/users/{ADDRESS}",
    f"https://api.polymarket.com/users/{ADDRESS}",
    f"https://api.polymarket.com/profile/{ADDRESS}",
    f"https://gamma-api.polymarket.com/query?query=users&address={ADDRESS}",
    f"https://clob.polymarket.com/profile/{ADDRESS}",
    f"https://strapi-matic.polymarket.com/profiles?address={ADDRESS}",
    f"https://gamma-api.polymarket.com/profiles/{ADDRESS}",
    # Try the data API with different paths
    f"https://data-api.polymarket.com/users/{ADDRESS}",
    f"https://data-api.polymarket.com/profile/{ADDRESS}",
    f"https://data-api.polymarket.com/leaderboard/{ADDRESS}",
]

for url in endpoints:
    try:
        resp = requests.get(url, timeout=5, headers=headers)
        status = resp.status_code
        body = resp.text[:200] if resp.text else ""
        print(f"{status} {url}")
        if status == 200:
            print(f"  {body}")
    except Exception as e:
        print(f"ERR {url}: {e}")
