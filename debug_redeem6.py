"""Check missing activities from API."""
import requests

address = "0xbdcd1a99fa4b4e8e69608ed1f1f5e1b86e244578"

for atype in ['SPLIT', 'REWARD', 'REDEEM', 'MERGE']:
    url = f"https://data-api.polymarket.com/activity?user={address}&type={atype}&limit=500"
    r = requests.get(url, timeout=30)
    data = r.json()
    total_usdc = sum(float(d.get('usdcSize', 0)) for d in data)
    print(f"{atype}: {len(data)} items, total USDC: ${total_usdc:,.2f}")

# Check the subgraph PnL source  
print("\nChecking PnL from subgraph...")
url = f"https://data-api.polymarket.com/pnl?address={address}"
r = requests.get(url, timeout=30)
print(f"  pnl endpoint: status={r.status_code}")
if r.status_code == 200:
    print(f"  data: {r.json()}")

# Try the positions endpoint
url = f"https://data-api.polymarket.com/positions?address={address}"
r = requests.get(url, timeout=30)
print(f"\npositions endpoint: status={r.status_code}, items={len(r.json()) if r.status_code==200 else 'N/A'}")
if r.status_code == 200:
    data = r.json()
    total_realized = sum(float(d.get('realizedPnl', 0)) for d in data)
    total_size = sum(float(d.get('size', 0)) for d in data)
    print(f"  Sum realizedPnl: ${total_realized:,.2f}")
    print(f"  Sum size: {total_size:,.2f}")
    for d in data[:3]:
        print(f"  Sample: realized={d.get('realizedPnl')} size={d.get('size')} asset={str(d.get('asset',''))[:20]}")
