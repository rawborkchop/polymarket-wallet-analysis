import requests

addr = '0x8278252ebbf354eca8ce316e680a0eaf02859464'

# Activity with correct 'user' param
url = f'https://data-api.polymarket.com/activity?user={addr}&limit=5'
r = requests.get(url, timeout=10)
print(f'Activity (user param): status={r.status_code}, count={len(r.json()) if r.status_code==200 else r.text[:200]}')
if r.status_code == 200:
    for item in r.json()[:3]:
        print(f'  type={item.get("activity_type","")} ts={item.get("timestamp","")}')

# Trades 
url2 = f'https://data-api.polymarket.com/trades?user={addr}&limit=5'
r2 = requests.get(url2, timeout=10)
print(f'\nTrades (user param): status={r2.status_code}, count={len(r2.json()) if r2.status_code==200 else r2.text[:200]}')

# Also try /trades?address=
url3 = f'https://data-api.polymarket.com/trades?address={addr}&limit=5&offset=0'
r3 = requests.get(url3, timeout=10)
print(f'Trades (address param): status={r3.status_code}, count={len(r3.json()) if r3.status_code==200 else r3.text[:200]}')
