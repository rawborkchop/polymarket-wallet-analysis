# How Polymarket Calculates Profile PnL

## TL;DR

The PnL figures shown on Polymarket profile pages (1D, 1W, 1M, ALL) come from the **leaderboard API**, not from summing positions or activity data.

## The API Endpoint

```
GET https://data-api.polymarket.com/v1/leaderboard?timePeriod={period}&orderBy=PNL&limit=1&offset=0&category=overall&user={address}
```

**Valid `timePeriod` values:** `all`, `month`, `week` (also supports `day` likely via VOL ordering)

**Response example:**
```json
{
  "rank": "13596",
  "proxyWallet": "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c",
  "userName": "1pixel",
  "vol": 773199.66,
  "pnl": 20172.77
}
```

## Verified Values (2026-02-16)

| Period | Leaderboard `pnl` | Frontend Display |
|--------|-------------------|------------------|
| ALL    | $20,172.77        | $20,172.77 ✅     |
| month  | $710.14           | (1M button)      |
| week   | $0.04             | (1W button)      |

The ALL-time PnL from the leaderboard API **exactly matches** the frontend display.

## Other API Endpoints (What They DON'T Provide)

### Positions API
```
GET https://data-api.polymarket.com/positions?user={addr}&sizeThreshold=0
```
- Returns **only current/active positions** (33 for this wallet)
- Does NOT include historical closed positions
- Fields: `realizedPnl`, `cashPnl`, `initialValue`, `currentValue`
- `cashPnl = currentValue - initialValue` (unrealized P&L per position)
- `realizedPnl` = profit from partial sells/redeems on that position
- Sum of `realizedPnl + cashPnl` across current positions = $2,313.12 (NOT the profile PnL)

### Activity API
```
GET https://data-api.polymarket.com/activity?user={addr}&limit=100&offset=N
```
- Paginated, max ~3100 entries before 400 error
- Types: TRADE (with side=BUY/SELL), REDEEM, MERGE, CONVERSION
- Activity goes back ~30 days for this wallet (Jan 17 - Feb 15, 2026)
- Computing `(SELL_usdc + REDEEM_usdc + MERGE_usdc) - BUY_usdc` from all activity = $1,886.65
- This does NOT match any displayed PnL value

### User Stats API (v1)
```
GET https://data-api.polymarket.com/v1/user-stats?proxyAddress={addr}
```
Returns: `trades`, `largestWin`, `views`, `joinDate` — no PnL data.

### Value API
```
GET https://data-api.polymarket.com/value?user={addr}
```
Returns current positions value only: `{"user": "...", "value": 20.2879}`

### Traded API
```
GET https://data-api.polymarket.com/traded?user={addr}
```
Returns trade count only: `{"user": "...", "traded": 1782}`

## How PnL Is Likely Computed (Server-Side)

The leaderboard PnL is computed **server-side** by Polymarket. Based on the data:

1. **It's NOT** a simple sum of positions API fields (those only cover active positions)
2. **It's NOT** directly derivable from the activity API (we get $1,886.65 vs $20,172.77)
3. **It IS** likely computed from the full trade/settlement history on-chain or in their internal database
4. **Formula (probable):** `PnL = (total USDC received from redeems + sells) - (total USDC spent on buys)` across ALL historical trades, not just the ones visible in paginated APIs

The leaderboard endpoint is the **only public API** that exposes the pre-computed PnL values shown on profiles.

## Key Findings

1. **Positions endpoint is incomplete** — only shows current positions with `size > 0`, not historical
2. **Activity endpoint is limited** — caps at ~3100 entries, can't get full history for active traders
3. **PnL is pre-computed server-side** — stored in the leaderboard/ranking system
4. **Time-windowed PnL** (1D/1W/1M) uses `timePeriod` param on leaderboard endpoint
5. The `$20,172.75` the user saw likely shifted to `$20,172.77` by the time we checked (live PnL changes with market prices)

## To Replicate PnL Display

```python
import urllib.request, json

def get_pnl(address, period="all"):
    url = f"https://data-api.polymarket.com/v1/leaderboard?timePeriod={period}&orderBy=PNL&limit=1&offset=0&category=overall&user={address}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    return data[0]["pnl"] if data else None

# Usage
addr = "0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c"
print(f"ALL: ${get_pnl(addr, 'all'):.2f}")
print(f"1M:  ${get_pnl(addr, 'month'):.2f}")
print(f"1W:  ${get_pnl(addr, 'week'):.2f}")
```
