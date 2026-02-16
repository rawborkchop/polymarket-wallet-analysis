# How open-source tools calculate Polymarket PnL

**Every major open-source Polymarket project uses weighted average cost basis — not FIFO or LIFO — to calculate profit and loss.** The official Polymarket Data API at `data-api.polymarket.com` pre-computes PnL using this method and exposes it through the `/positions` endpoint, which most third-party tools simply consume rather than recomputing independently. Fees are conspicuously absent from all API responses — they are silently embedded in execution prices, creating a significant blind spot for anyone trying to reconcile calculated PnL against actual cash flows. The ecosystem spans roughly 20+ GitHub repositories, but only a handful implement PnL logic from scratch; the rest delegate to Polymarket's own infrastructure.

---

## The universal formula: weighted average cost, never FIFO

Across every repository examined — from Polymarket's official PnL subgraph to community-built tools like `leolopez007/polymarket-trade-tracker`, `PaulieB14/Polymarkets-Profit-and-Loss`, and `sarviinageelen/polymarket-sports-analytics` — the PnL calculation follows one consistent pattern. The core formulas, verified against actual API response data, are:

**Average cost basis update on each buy:**
```
new_avgPrice = (old_avgPrice × old_quantity + fill_price × fill_quantity) / (old_quantity + fill_quantity)
```

**Unrealized PnL (called `cashPnl` in the API):**
```
initialValue = avgPrice × current_size
currentValue = curPrice × current_size
cashPnl = currentValue - initialValue
percentPnl = (cashPnl / initialValue) × 100
```

**Realized PnL (from sells and redemptions):**
```
realizedPnl += (sell_price - avgPrice_at_time_of_sale) × quantity_sold
```

These formulas were directly validated against live API data: for a position with `avgPrice = 0.020628`, `size = 90,548.09`, and `curPrice = 0.0645`, the computed `initialValue` of **$1,867.83** and `currentValue` of **$5,840.35** match the API response to the cent. The `cashPnl` of **$3,972.53** is simply the difference.

Partial fills are handled naturally by this system. Each fill — whether partial or complete — triggers a weighted average recalculation. The Polymarket exchange contract emits individual `OrderFilled` events for each fill, and on-chain subgraphs process each independently. When tokens are sold, the average price is **not** recalculated — only the position size decreases, and the price delta between the sale price and the running average generates realized PnL.

The `PaulieB14/Polymarkets-Profit-and-Loss` subgraph makes this explicit in its GraphQL schema, storing `avgPrice`, `amount`, `realizedPnl`, and `totalBought` as first-class fields on the `TokenPosition` entity, with account-level aggregates for `totalRealizedPnl`, `totalUnrealizedPnl`, `winRate`, `profitFactor`, and `maxDrawdown`.

**For resolved markets**, the formula simplifies: winning tokens redeem at exactly **$1.00** each, losing tokens at **$0.00**. So realized PnL on redemption = `(1.00 - avgPrice) × quantity` for winners, or `(0.00 - avgPrice) × quantity` for losers. The Data API flags these with `redeemable: true`, and the `/activity` endpoint records them as `type: "REDEEM"`.

---

## Six APIs power the ecosystem, but Data API dominates PnL work

Open-source projects interact with Polymarket through six distinct API systems, each serving a different role. Understanding which to use for what is critical:

| API | Base URL | Primary use | Auth |
|-----|----------|-------------|------|
| **Data API** | `data-api.polymarket.com` | Positions, PnL, trade history, activity | None |
| **Gamma API** | `gamma-api.polymarket.com` | Market discovery, metadata, events | None |
| **CLOB API** | `clob.polymarket.com` | Order book, prices, order placement | Read: No; Write: HMAC |
| **WebSocket** | `wss://ws-subscriptions-clob.polymarket.com` | Real-time price streams | Optional |
| **PnL Subgraph** | `api.goldsky.com/.../pnl-subgraph/...` | On-chain PnL via GraphQL | None |
| **The Graph** | `gateway.thegraph.com/api/{key}/subgraphs/...` | On-chain market/position data | API key |

**The Data API's three core endpoints for PnL work:**

**`GET /positions`** returns pre-calculated PnL per position. Key parameters: `user` (proxy wallet, required), `limit` (max 500), `offset`, `sizeThreshold`, `redeemable`, `sortBy` (supports `CASHPNL`, `PERCENTPNL`, `TOKENS`, `CURRENT`, `INITIAL`). Response includes `avgPrice`, `initialValue`, `currentValue`, `cashPnl`, `realizedPnl`, `curPrice`, `size`, `totalBought`, `negativeRisk`, `redeemable`, and the complementary token via `oppositeAsset`.

**`GET /activity`** returns the full on-chain activity log. Parameters: `user` (required), `type` (filter: `TRADE`, `SPLIT`, `MERGE`, `REDEEM`, `REWARD`, `CONVERSION`), `start`/`end` timestamps, `side` (`BUY`/`SELL`), `limit`/`offset`. Each record includes `size` (shares), `usdcSize` (dollar amount), `price`, `asset` (token ID), and `transactionHash`. Critically, **no fee field exists** in the response.

**`GET /trades`** returns trade history with `side`, `size`, `price`, `timestamp`, `transactionHash`, and market metadata. Also **lacks fee data**. Supports filtering by `user`, `market` (conditionId), `side`, and amount thresholds.

**Pagination is offset-based** across all Data API endpoints: increment `offset` by `limit` until the result count drops below `limit`. Maximum `limit` is **500**, and the maximum practical `offset` is approximately **10,000** — meaning heavy traders with more than 10,000 activity records cannot retrieve complete history through simple sequential pagination. The workaround used by projects like `razrfly/volfefe` is time-windowed queries using `start`/`end` timestamp parameters.

**The standard data reconstruction pattern** used by most projects follows three stages: (1) periodic market sync via Gamma API's `GET /markets?closed=false&limit=100`, (2) trade history backfill via Data API's `GET /trades?market={id}&limit=100&offset=0` with incrementing offsets, and (3) continuous polling of `GET /trades?limit=100` every 30 seconds for new activity. Deduplication relies on `transactionHash` as a unique key.

**ID mapping** flows from Gamma API to Data API: `GET /markets` returns `slug`, `conditionId`, and `clobTokenIds` (array of YES/NO token IDs). The `conditionId` is then used as the `market` parameter in Data API calls, while individual `clobTokenIds` (large integer strings) map to `asset` fields in position and trade data.

---

## Where the fees hide and why PnL numbers diverge

The single most important fact for anyone building a Polymarket PnL calculator: **fees are invisible in the API data.** Neither `/positions`, `/activity`, nor `/trades` returns a fee field. This creates several categories of discrepancies between independently calculated PnL and what Polymarket's UI shows.

**The fee structure itself is non-trivial.** According to Polymarket's official CLOB documentation, fees follow a price-dependent parabolic formula:

```
For selling tokens:  feeQuote = baseRate × min(price, 1 - price) × size
For buying tokens:   feeBase  = baseRate × min(price, 1 - price) × (size / price)
```

The `min(price, 1 - price)` term creates fees that peak at **p = 0.50** and drop to near-zero at price extremes. At a 50-cent price, the effective fee is approximately **1.56%** of trade value; at 10 cents, it drops to roughly **0.20%**. Importantly, **`fee_rate_bps` varies by market** and must be fetched dynamically per token — it is not universal.

While Polymarket's public-facing documentation states "Polymarket does not charge any type of fee," this is outdated. Most markets currently operate fee-free, but **15-minute crypto markets** (BTC, ETH, SOL, XRP) carry taker fees, and the fee schedule is explicitly marked "subject to change." Maker rebates are distributed daily from a taker fee pool — tracked in the `/activity` endpoint as `type: "MAKER_REBATE"` — but are not per-fill rebates.

**Beyond fees, five other pitfalls cause PnL discrepancies:**

**Double-counting from on-chain events.** Paradigm Research documented in December 2025 that each Polymarket trade emits multiple `OrderFilled` events — one per maker plus a redundant taker-focused event — meaning anyone computing PnL from raw blockchain events can **double-count trades by ~100%**. The correct approach is to use only maker-side events or the single `OrdersMatched` event per trade. The Data API already deduplicates, but on-chain subgraph builders must handle this explicitly.

**Split, Merge, and Conversion operations.** Polymarket's matching engine doesn't always execute simple swaps. A trade can involve splitting $1 USDC into 1 YES + 1 NO token, then selling the unwanted side. These operations appear as separate activity types (`SPLIT`, `MERGE`, `CONVERSION`) in the API. The `leolopez007/polymarket-trade-tracker` and `chainstacklabs/polyclaw` repos handle this correctly — when you split USDC and sell the NO side, your YES cost basis should be `$1.00 - NO_sale_price`. Most simpler bots miss this entirely.

**Negative risk market conversions.** Markets flagged `negativeRisk: true` (common in multi-outcome events like elections) use a special adapter contract that allows one-way conversion of NO tokens into YES tokens plus USDC. These conversions change effective cost basis and appear as `type: "CONVERSION"` in the activity feed. Only the `leolopez007` tracker and on-chain subgraphs handle this.

**NO position PnL inversion.** The `NYTEMODEONLY/polyterm` changelog reveals a telling bug fix: "Database P&L wrong for NO positions: Position summary now correctly calculates profit/loss for NO-side positions." When the NO price falls, a naive implementation might show a loss — but falling NO price means rising YES probability, which is indeed bad for NO holders. The subtlety is that YES and NO tokens are tracked as completely separate positions with independent `avgPrice` and `size` values, linked by `oppositeOutcome` and `oppositeAsset` fields.

**Pagination truncation and timing delays.** With a max offset of ~10,000 records, power traders can lose historical data. Additionally, the Data API indexes on-chain data with a delay — trades may appear in the API seconds to minutes after on-chain confirmation, causing temporary discrepancies with the UI. Gas fees on Polygon (~$0.01–$0.50 per transaction) are never included in any PnL calculation.

---

## The key repositories and what each actually computes

The open-source landscape divides into three tiers: infrastructure that computes PnL, tools that consume pre-computed PnL, and bots that track simple entry/exit prices.

**Tier 1 — PnL computation from on-chain data:**

`Polymarket/polymarket-subgraph` (121 stars) contains the official `pnl-subgraph/` directory deployed on Goldsky. It processes `OrderFilled` events from the CTF Exchange contract (`0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`) and `Transfer`, `Split`, `Merge`, `Redeem` events from the Conditional Tokens contract (`0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`). This is the canonical source feeding the Data API.

`PaulieB14/Polymarkets-Profit-and-Loss` reimplements a comprehensive PnL subgraph with `Account`-level aggregates (`totalRealizedPnl`, `winRate`, `profitFactor`, `maxDrawdown`) and `TokenPosition`-level tracking (`avgPrice`, `realizedPnl`, `totalBought`). It indexes the same contracts starting at Polygon block 20,000,001.

**Tier 2 — Tools consuming pre-computed PnL:**

`leolopez007/polymarket-trade-tracker` (25 stars) is the most complete standalone tool. It pulls from the Data API, Gamma API, and Polygon RPC to identify maker/taker roles, detect trade sources (Direct, Neg-Risk, Split, Merge, Transfer, Redeem), and generate cumulative PnL charts. Its `neg_risk.py` module specifically handles negative-risk market conversions.

`sarviinageelen/polymarket-sports-analytics` queries the Goldsky PnL subgraph for position data, then computes weekly PnL breakdowns, rolling accuracy, and streak analysis. It filters out late entries at >95% probability for signal quality.

**Tier 3 — Bots with basic PnL tracking:**

`Trust412/Polymarket-spike-bot-v1` uses simple percentage-based PnL: `(currentPrice - entryPrice) / entryPrice` with fixed take-profit (3%) and stop-loss (-2.5%) thresholds. No position averaging, no cost basis tracking.

`chainstacklabs/polyclaw` stores entry prices locally and computes live PnL against Gamma API prices, with explicit split+CLOB execution flow handling.

---

## Conclusion

The Polymarket PnL calculation ecosystem is more uniform than it appears: **weighted average cost basis is the universal standard**, implemented at the subgraph level and propagated through the Data API to every downstream tool. The critical technical challenges are not in the core formula but in the edges — handling Split/Merge/Conversion operations that alter cost basis, correctly processing negative-risk market mechanics, avoiding double-counting from redundant on-chain events, and accounting for fees that the API deliberately hides inside execution prices. Anyone building an independent PnL calculator should start by consuming the Data API's `/positions` endpoint (which handles all of this correctly), and only attempt independent computation from raw trade data if they need to audit discrepancies or track fee impact — in which case they must process all seven activity types (`TRADE`, `SPLIT`, `MERGE`, `REDEEM`, `REWARD`, `CONVERSION`, `MAKER_REBATE`) and apply the `baseRate × min(p, 1-p) × size` fee formula with per-token `fee_rate_bps` values.