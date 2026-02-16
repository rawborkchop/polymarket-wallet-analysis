import requests
addr = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
endpoints = ['revenue', 'pnl-timeseries', 'portfolio', 'positions', 'earnings', 
             'profit-loss', 'activity', 'trades', 'history']
for ep in endpoints:
    try:
        r = requests.get(f"https://data-api.polymarket.com/{ep}?user={addr}", timeout=10)
        size = len(r.text)
        print(f"{ep}: {r.status_code} ({size} bytes)")
        if r.status_code == 200 and size < 500:
            print(f"  -> {r.text[:200]}")
    except Exception as e:
        print(f"{ep}: ERROR {e}")
