"""Try more PM API endpoints to understand PnL calculation."""
import json, urllib.request

addr = '0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c'
headers = {'User-Agent': 'Mozilla/5.0'}

endpoints = [
    f'https://data-api.polymarket.com/v1/users/{addr}',
    f'https://data-api.polymarket.com/v1/profit-loss?address={addr}',
    f'https://data-api.polymarket.com/v1/pnl?address={addr}',
    f'https://data-api.polymarket.com/v1/positions?address={addr}&limit=5',
    f'https://data-api.polymarket.com/v1/portfolio?address={addr}',
    f'https://data-api.polymarket.com/v1/users/{addr}/pnl',
    f'https://data-api.polymarket.com/v1/user-pnl?proxyWallet={addr}',
    f'https://data-api.polymarket.com/v1/leaderboard/rank?proxyWallet={addr}',
    f'https://gamma-api.polymarket.com/positions?user={addr}&limit=3',
    f'https://data-api.polymarket.com/v1/leaderboard?timePeriod=all&orderBy=PNL&limit=1&offset=0&category=overall&user={addr}',
]

for url in endpoints:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            try:
                j = json.loads(data)
                # Truncate large responses
                s = json.dumps(j, indent=2)
                if len(s) > 2000:
                    s = s[:2000] + '...'
                print(f"\nOK {url}\n{s}")
            except:
                print(f"\nOK {url}\n{data[:500]}")
    except Exception as e:
        print(f"\nFAIL {url}\n  {e}")
