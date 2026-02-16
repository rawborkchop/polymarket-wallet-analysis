# Cash Flow PnL Report — 30 Days (2026-01-16 to 2026-02-15)

**Wallet:** 1pixel (id=7)  
**Target (Polymarket official):** $1,282.17

## Raw Numbers

| Component | Count | Amount |
|-----------|------:|-------:|
| BUY trades | 2,532 | -$32,918.67 |
| SELL trades | 547 | +$11,957.96 |
| REDEEM activities | 346 | +$23,681.71 |
| SPLIT activities | 0 | $0.00 |
| MERGE activities | 5 | +$643.75 |
| CONVERSION (excluded) | 2 | $116.65 |
| REWARD (excluded) | 0 | $0.00 |

## Results

| Metric | Value |
|--------|------:|
| **Trade-only PnL** (sell - buy) | **-$20,960.72** |
| **Full cash flow PnL** | **$3,364.74** |
| Polymarket official | $1,282.17 |
| **Difference** | **+$2,082.57** |

## Analysis

The simple cash-flow approach gives **$3,364.74**, which is **$2,082.57 higher** than Polymarket's $1,282.17.

### Why the discrepancy?

Cash-flow PnL doesn't account for **position changes** across the period boundary:

- **Positions opened before Jan 16 but closed during the period** — the sell/redeem revenue counts as inflow, but the original buy cost (before the window) is NOT counted as outflow. This **inflates** the cash-flow PnL.
- **Positions opened during the period but still open on Feb 15** — the buy cost counts as outflow, but no corresponding sell/redeem yet. This **deflates** the cash-flow PnL.

The net effect here is +$2,082.57 inflation, meaning the wallet likely redeemed/sold positions during this period that were originally bought *before* Jan 16 (old positions paying out), which more than offsets unrealized positions opened in the window.

### Conclusion

A pure cash-flow approach is unsuitable for windowed PnL. Polymarket likely uses a **cost-basis or mark-to-market** method that accounts for position inventory at period boundaries. The $1,282.17 figure requires either:
1. Cost-basis tracking with opening/closing inventory
2. Mark-to-market with position values at start and end of period
