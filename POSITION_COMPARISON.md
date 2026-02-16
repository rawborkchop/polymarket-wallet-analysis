# Position Comparison: Our Calculator vs Polymarket API

## Counts
- Polymarket API positions: 33 (only returns ACTIVE positions)
- Our positions: 1901 (includes all historical)
- Common: 27
- Only ours: 1874 (historical/closed - can't verify against PM)
- Only PM: 6 (we're missing these entirely)

## Totals
- Our realized PnL (cost basis): $42,299.92
- Our cash_flow_pnl: $19,283.18
- PM sum(realizedPnl): $3,004.86
- PM sum(cashPnl): $-691.74
- PM cashPnl + realizedPnl: $2,313.12
- **Expected total PnL: ~$20,172**

## The Core Problem

**Our cost basis calculator reports $42,300 — MORE THAN DOUBLE the correct ~$20,172.**

The cash_flow_pnl ($19,283) is much closer to reality.

## Gap Breakdown

| Source | Amount |
|--------|--------|
| Gap from common positions (ours vs PM) | -$545.37 |
| PnL from only-ours positions (1,874 historical) | +$40,947.57 |
| **Total gap (ours - PM realized)** | **+$39,295.06** |

The gap is almost entirely from **1,874 historical positions** that PM's API doesn't return. We can't verify those individually, but the total is wildly inflated.

## Evidence of Double-Counting

The cost basis calculator reports $42,300 while the cash flow method reports $19,283 for the **same wallet, same trades**. Since cash flow is simple (money out - money in), it's likely correct. The cost basis method is **overcounting by ~$23,000**.

Likely culprit: **SPLIT/MERGE + BUY/SELL double-counting**. When a user:
1. SPLITs USDC into YES+NO tokens (creates positions at $0.50 each)
2. SELLs one side on the order book

The SPLIT creates positions, and if the same tokens also appear as BUY trades in the order book data, the cost basis gets double-entered. The SELL then realizes PnL against an artificially low cost basis.

Similarly for MERGEs: the MERGE reduces positions, but if the corresponding BUY of both sides was already tracked as separate BUY events, the merge realizes PnL that was already captured.

## Common Position Differences

For the 27 positions we CAN compare:
- Our total: $1,304.66
- PM total: $1,850.03
- We're **under** by $545 on matched positions

Top diffs are NYC temperature markets where PM shows more `totalBought` than us (e.g., PM=634 vs ours=29), suggesting we're missing some trades for active positions.

## Missing Positions (in PM but not ours)

6 positions totaling $1,154.83 in PM realizedPnl that we don't track at all. All NYC temperature markets — likely from trades we haven't fetched.

## Key Findings

1. **The cost basis calculator overcounts by ~2x** ($42,300 vs ~$20,172 expected)
2. **Root cause is likely in how SPLITs/MERGEs interact with BUY/SELL trades** — tokens acquired via SPLIT are also showing up as BUY events, creating double cost basis entries
3. **The cash flow method ($19,283) is much more reliable** as a sanity check
4. **PM API only returns active positions** — useless for verifying historical PnL
5. **76 split-placeholder positions exist** with $0 PnL (not directly causing the issue, but indicating split activity)
6. **We're also missing 6 active positions** and undercounting bought amounts on others
