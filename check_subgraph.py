import requests, json

SUBGRAPH_URL = "https://api.goldsky.com/api/public/project_cl9gqp4nj0014l80zbb9ggz4m/subgraphs/polymarket-pnl/0.0.4/gn"

wallets = [
    "0xee613b3fc183ee44f9da9c05f53e2da107e3debf",
    "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c",
]

for w in wallets:
    query = f'''{{
        globals(where: {{id: "{w}"}}) {{
            id realizedPnl scaledRealizedPnl numTrades currentCost
        }}
    }}'''
    resp = requests.post(SUBGRAPH_URL, json={"query": query})
    data = resp.json()
    print(f"\n=== {w[:10]}... ===")
    print(json.dumps(data, indent=2))
