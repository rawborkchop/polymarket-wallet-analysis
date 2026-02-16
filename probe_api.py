import requests
s = requests.Session()
s.headers.update({'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0'})
addr = '0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c'

paths = [
    f'/profile?user={addr}',
    f'/profiles?user={addr}',
    f'/pnl?user={addr}',
    f'/pnl?user={addr}&window=all',
    f'/leaderboard?user={addr}',
    f'/leaderboard?user={addr}&window=all',
    f'/rewards?user={addr}',
    f'/activity?user={addr}&limit=1&type=REWARD',
]

for path in paths:
    try:
        r = s.get(f'https://data-api.polymarket.com{path}', timeout=5)
        body = r.text[:300] if r.ok else ''
        print(f'{r.status_code} {path}')
        if body:
            print(f'  {body}')
    except Exception as e:
        print(f'ERR {path}: {e}')
