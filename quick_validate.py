import requests
from collections import Counter

w = '0x8278252ebbf354eca8ce316e680a0eaf02859464'

# Official PnL
print("=== PM OFFICIAL ===")
for p in ['all', 'month', 'week', 'day']:
    r = requests.get(f'https://data-api.polymarket.com/v1/leaderboard?timePeriod={p}&user={w}')
    d = r.json()
    if d:
        print(f"  {p:6s}: pnl={d[0]['pnl']:>12.2f}  vol={d[0]['vol']:>12.2f}")
    else:
        print(f"  {p:6s}: no data")

# Fetch activities
print("\n=== FETCHING ACTIVITIES ===")
acts = []
off = 0
while True:
    r = requests.get(f'https://data-api.polymarket.com/activity?user={w}&limit=500&offset={off}')
    d = r.json()
    if not d or not isinstance(d, list):
        break
    acts.extend(d)
    off += len(d)
    if len(d) < 500:
        break

print(f"Total: {len(acts)}")
print(Counter(a.get('type', '?') for a in acts if isinstance(a, dict)))

# Check if truncated
if len(acts) >= 3500:
    print("WARNING: Likely truncated at 3500!")
else:
    print("Data appears complete.")
