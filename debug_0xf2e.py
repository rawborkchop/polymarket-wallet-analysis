import requests

addr = '0x8278252ebbf354eca8ce316e680a0eaf02859464'

# Check PM profile for official numbers
r = requests.get(f'https://data-api.polymarket.com/v1/leaderboard?timePeriod=all&user={addr}', timeout=10)
d = r.json()[0]
print(f"PM ALL: pnl=${d.get('pnl')}, volume={d.get('volume')}, numTrades={d.get('numTrades')}")

# Check our volume vs PM
# Our volume = sum(size) of all trades
# We have 12,279 trades
print(f"\nOur trades: 12,279")
print(f"PM numTrades: {d.get('numTrades')}")
print(f"PM volume: {d.get('volume')}")
