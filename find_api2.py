import requests, json
addr = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"

# positions endpoint
r = requests.get(f"https://data-api.polymarket.com/positions?user={addr}", timeout=30)
data = r.json()
print(f"Positions: {len(data)} entries")
if data:
    # Sum realized PnL
    total_realized = sum(float(d.get('realizedPnl', 0)) for d in data)
    total_initial = sum(float(d.get('initialValue', 0)) for d in data)
    total_current = sum(float(d.get('currentValue', 0)) for d in data)
    print(f"Sum realizedPnl: ${total_realized:,.2f}")
    print(f"Sum initialValue: ${total_initial:,.2f}")  
    print(f"Sum currentValue: ${total_current:,.2f}")
    print(f"\nSample entry keys: {list(data[0].keys())}")
    print(f"\nTop 3 by realizedPnl:")
    sorted_data = sorted(data, key=lambda x: abs(float(x.get('realizedPnl', 0))), reverse=True)
    for d in sorted_data[:3]:
        print(f"  pnl=${d.get('realizedPnl')} initial=${d.get('initialValue')} current=${d.get('currentValue')} size={d.get('size')} outcome={d.get('outcome')}")
