# Polymarket Leaderboard API & PnL Analysis

## 1. Leaderboard API

### Endpoint
```
GET https://data-api.polymarket.com/v1/leaderboard
  ?timePeriod={period}
  &orderBy=PNL
  &limit=1&offset=0
  &category={category}
  &user={address}
```

### Valid Parameters
- **timePeriod**: `all`, `month`, `week`, `day` (others return 400)
- **category**: `overall`, `weather`, `sports`, `politics`, `crypto` (pop-culture/science return empty)
- **orderBy**: `PNL` (possibly others)
- User-Agent header required

### Response Fields
```json
{
  "rank": "4511",
  "proxyWallet": "0xbdcd1a99...",
  "userName": "1pixel",
  "xUsername": "",
  "verifiedBadge": false,
  "vol": 773199.66,     // total shares traded (not USD volume)
  "pnl": 20172.77,      // realized PnL in USD
  "profileImage": "..."
}
```

### 1pixel Values (fetched 2026-02-16)
| Period | PM PnL | PM Vol |
|--------|--------|--------|
| all | $20,172.77 | 773,199.66 |
| month | $710.14 | 39,257.10 |
| week | $0.04 | — |
| day | $0.04 | — |

### Category Breakdown (all-time)
| Category | PnL |
|----------|-----|
| weather | $20,472.34 |
| sports | -$94.30 |
| politics | -$38.59 |
| crypto | -$102.32 |
| **Sum** | **$20,237.13** |
| **overall** | **$20,172.77** |

Note: Sum of categories ($20,237) ≠ overall ($20,173). Difference of $64 suggests rounding or uncategorized markets.

### Other API Endpoints
Only the leaderboard endpoint works. All others return 404/400:
- `/v1/users/{addr}`, `/v1/profit-loss`, `/v1/pnl`, `/v1/portfolio` — 404
- `/v1/positions?address=` — 400
- `gamma-api.polymarket.com/positions` — 404

---

## 2. How PM Calculates PnL

### Source: Open-source PnL Subgraph
GitHub: `Polymarket/polymarket-subgraph/pnl-subgraph`

**Schema** (`UserPosition` entity):
- `amount`: shares held
- `avgPrice`: weighted average purchase price
- `realizedPnl`: cumulative realized profit/loss
- `totalBought`: cumulative shares bought

**Formula per position:**

| Event | Effect |
|-------|--------|
| **BUY** | `avgPrice = (avgPrice * amount + buyPrice * buyAmount) / (amount + buyAmount)`; `amount += buyAmount` |
| **SELL** | `realizedPnl += min(sellAmount, amount) * (sellPrice - avgPrice)`; `amount -= adjusted` |
| **SPLIT** | Buy BOTH Yes+No at $0.50 each |
| **MERGE** | Sell BOTH Yes+No at $0.50 each |
| **REDEEM** | Sell winner at $1.00, loser at $0.00 |
| **CONVERSION** | Neg-risk adapter conversion (complex) |

**Total PnL** = Σ realizedPnl across all positions

### Key Difference from Cash Flow
- **Cash flow**: counts actual USDC in/out (buys, sells, redeems, splits, merges)
- **PM PnL**: tracks per-position cost basis and realized gain/loss on each sell
- These are NOT the same! Cash flow double-counts some operations (e.g., split costs USDC but the PnL subgraph tracks it as buying at 0.50)

---

## 3. Period-Based PnL (Monthly/Weekly)

### Approach: Snapshot Difference
PM monthly PnL = `total_realized_pnl(now) - total_realized_pnl(30_days_ago)`

This is **NOT** the same as filtering trades to the last 30 days, because:
- A sell today uses avgPrice from historical buys
- The snapshot captures the cumulative effect correctly

### Our Simulation Results

| Period | Our Sim | PM Official | Diff | Error% |
|--------|---------|-------------|------|--------|
| all | $22,519 | $20,173 | +$2,346 | +11.6% |
| month | $745 | $710 | +$35 | +4.9% |
| week | -$119 | $0.04 | -$119 | — |
| day | -$119 | $0.04 | -$119 | — |

### Why the Gaps?

**All-time gap (+$2,346):**
- 1,396 redeems skipped (markets with no trade-based asset mapping)
- 258 splits skipped (same reason)
- 254 conversions completely ignored ($21,493 USDC)
- 1,594/1,782 markets only have 1 outcome in our trade data (neg-risk markets where user only traded one side)

**Month gap (+$35):** Very close! The snapshot method works. Small gap likely from same missing data.

**Week/Day gap:** A single redeem event is handled differently. PM shows $0.04, our sim shows -$119. This suggests our winner-inference for that specific redeem is wrong.

---

## 4. Comparison with Other Wallets

### sovereign2013
| Period | PnL |
|--------|-----|
| all | $1,578,454.25 |
| month | $237,507.34 |
| week | $12,449.17 |
| day | $12,449.17 |

### Top 5 All-Time
| Rank | PnL |
|------|-----|
| 1 | $22,053,934 |
| 2 | $16,619,507 |
| 3 | $10,870,855 |
| 4 | $8,709,973 |
| 5 | $7,807,266 |

---

## 5. Key Findings & Recommendations

### To Match PM's Monthly PnL:
1. **Use snapshot approach**: Simulate full history up to 30 days ago, then up to now, take the difference
2. **Must handle conversions**: 254 neg-risk conversions worth $21.5K affect all-time accuracy
3. **Need both outcomes per market**: Currently 89% of markets only have 1 outcome. Need the complement token IDs (from the condition/neg-risk event)
4. **Need resolution data**: Only 120/1,569 redeem markets have winner info in our DB

### Data Gaps to Fill:
- Fetch complement token IDs from PnL subgraph GraphQL or on-chain condition data
- Fetch market resolution outcomes for all redeemed markets
- Implement neg-risk conversion handling (NegRiskAdapterMapping.ts from subgraph)

### Current Accuracy:
- **Monthly PnL: 95% accurate** (good enough for most purposes)
- **All-time PnL: 88% accurate** (needs conversion handling)
- **Weekly/Daily: unreliable** (single event inference errors dominate)

### Volume Note:
PM's `vol` field = total shares traded (buy_size + sell_size), NOT dollar volume.
Our data: 771,862 shares vs PM's 773,200 (99.8% match).
