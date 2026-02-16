import requests, json
addr = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"

# Activity - check how many
r = requests.get(f"https://data-api.polymarket.com/activity?user={addr}&limit=5", timeout=30)
data = r.json()
print(f"Activity sample: {len(data)} entries")
if data:
    print(f"Keys: {list(data[0].keys())}")
    for d in data[:3]:
        print(f"  type={d.get('type')} asset={d.get('asset','')[:20]} outcome={d.get('outcome')} usdc={d.get('usdcSize')}")

# Trades
r2 = requests.get(f"https://data-api.polymarket.com/trades?user={addr}&limit=5", timeout=30)
data2 = r2.json()
print(f"\nTrades sample: {len(data2)} entries")
if data2:
    print(f"Keys: {list(data2[0].keys())}")
    for d in data2[:3]:
        print(f"  side={d.get('side')} asset={d.get('asset','')[:20]} outcome={d.get('outcome')} price={d.get('price')} size={d.get('size')}")

# Key question: is this the same wallet as in DB?
print(f"\nAPI wallet: {addr}")
print(f"DB wallet:  0xbdcd1a99fa4b4e8e69608ed1f1f5e1b86e244578")
print(f"Match: {addr == '0xbdcd1a99fa4b4e8e69608ed1f1f5e1b86e244578'}")
