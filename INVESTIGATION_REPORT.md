# PnL Gap Investigation Report — 1pixel Wallet

**Date:** 2026-02-16  
**Wallet:** 1pixel (id=7)  
**Our PnL:** $42,300 (cost basis) / $40,776 (cash flow)  
**Official PnL:** $20,173  
**Gap:** ~$22,127

---

## 1. PnL Breakdown by Event Type

| Source  | PnL       | Event Count |
|---------|-----------|-------------|
| REDEEM  | $26,052   | 283         |
| SELL    | $15,042   | 2,812       |
| MERGE   | $1,157    | 43          |
| REWARD  | $48       | 26          |
| CONVERSION | $0 (SKIPPED) | 0 of 254 |
| **TOTAL** | **$42,300** | |

## 2. Cash Flow Summary

| Flow | Amount |
|------|--------|
| Buy cost | $124,289 |
| Sell revenue | $79,828 |
| Redeem revenue | $83,618 |
| Split cost | $23,766 |
| Merge revenue | $3,844 |
| Reward revenue | $48 |
| Conversion revenue | $21,493 |
| **Cash flow PnL** | **$40,776** |

## 3. Root Causes Identified

### ROOT CAUSE #1: Missing Loser Redeem Losses (~$10K-15K estimated)

**The single biggest issue.** When a market resolves, losing positions should generate NEGATIVE PnL equal to their cost basis (you paid $X for tokens now worth $0). The system is failing to process most of these.

- **1,282 loser redeems** (usdc=0) in the data
- Only **47 generated PnL events** (out of 183 unique timestamps)
- **155 loser redeem timestamps** produced NO realized PnL event at all
- The 47 that DID fire show **+$2,991 PnL** — this is WRONG and indicates they're being misclassified or matched to wrong positions

**Why it happens:** The `_handle_redeem` method requires resolving the empty `asset` field to a position. For loser redeems, the 3-stage resolution often fails:
- Stage 1 (market_assets by outcome): Fails because outcome field is empty
- Stage 2 (market resolution inference): Only works if `Market.resolved=True` AND `winning_outcome` is set in DB — many markets show `resolved=False` despite having redeem activities
- Stage 3 (open position inference): Often fails because the winner redeem already consumed the "obvious" position, and the loser position may not have been created (split placeholders don't match)

**Impact:** Every missed loser redeem leaves the cost basis un-recognized. For positions bought at avg ~$0.30-0.50, this is $0.30-0.50 × size in missing losses per position.

### ROOT CAUSE #2: 254 CONVERSION Activities Completely Skipped ($21,493 USDC)

All 254 CONVERSION activities have **empty asset fields**. The `_handle_conversion` method returns early when `event.asset` is empty. These are on 79 markets with NO overlap with REDEEM markets.

CONVERSIONs are resolution payouts (like redeems but via a different mechanism). The $21,493 in USDC received is NOT generating any PnL events. However, the cost basis from the original BUYs for these markets remains in the positions, unclosed.

**Net effect is complex:**
- Missing positive PnL from winner conversions (USDC received - cost basis)
- Missing negative PnL from loser conversions (if any exist with usdc=0)
- Currently these positions remain "open" with cost basis locked up

### ROOT CAUSE #3: Massive Open Position Cost Basis ($58,670)

**1,458 positions** still show `quantity > 0` with a combined cost basis of **$58,670**. Many of these are from:
- Markets that resolved but redeems weren't matched to positions (root cause #1)
- Conversion markets where positions were never closed (root cause #2)
- Split-created positions using placeholder asset IDs (`{market_id}_split_YES`) that never match real asset IDs
- Active/unresolved markets (legitimate)

If all these open positions were correctly closed (losses recognized), PnL would drop to approximately **-$16,370** — which overshoots the other direction. The truth is somewhere in between: some are legitimate open positions, some should have been closed by redeems/conversions.

### ROOT CAUSE #4: Market Resolution Data Gaps

Many markets that have REDEEM activities show `resolved=False` in our DB. This breaks Stage 2 of the redeem asset resolution (market resolution inference), particularly for loser redeems which depend on knowing the winning outcome to infer the losing side.

### SECONDARY: 65 Oversold Positions

65 positions show `total_sold > total_bought`. This is a counter bug (`pos.total_sold += event.size` uses full size instead of capped `sell_size`), but does NOT affect PnL calculation since PnL uses the capped `sell_size`.

## 4. Markets with Both SELL and REDEEM PnL

**119 markets** have both SELL and REDEEM PnL events. Total PnL in these markets: **$16,898**.

However, deep-dive analysis shows these are **mostly legitimate** — the wallet partially sells some tokens before resolution, then redeems the remainder. Token flow balances out (bought + splits ≥ sold + redeemed).

Top examples:
- Market 9428 (London 8°C): Bought 1,664 → Sold 370 + Redeemed 1,294 = 0 remaining ✓
- Market 10565 (London 76°F): Bought 2,910 → Sold 495 + Redeemed 2,415 = 0 remaining ✓

**These are NOT double-counted.** The sell and redeem operate on different portions of the same position.

## 5. Quantifying the Gap

| Factor | Estimated Impact |
|--------|-----------------|
| Missing loser redeem losses | -$10K to -$15K (est.) |
| Conversion PnL not tracked | Complex (net ~±$5K) |
| Unclosed positions from resolution gaps | -$5K to -$10K (est.) |
| **Estimated correction** | **-$15K to -$25K** |
| **Target (to reach official $20K)** | **-$22K** |

## 6. Proposed Fixes (DO NOT IMPLEMENT)

### Fix 1: Handle Empty-Asset Conversions
Add asset resolution logic to `_handle_conversion` similar to `_handle_redeem` (3-stage resolution). This closes 79 markets worth of positions.

### Fix 2: Improve Loser Redeem Resolution
- **Backfill Market.resolved and Market.winning_outcome** from the Polymarket API for all markets with REDEEM activities
- Improve Stage 3 (position inference) for loser redeems — if winner was already consumed, check ALL positions for the market (not just open ones) to find the losing side's asset ID
- Consider using the Activity API's complementary data (each market resolution produces both winner and loser redeems at the same timestamp — use winner's resolved asset to infer loser's)

### Fix 3: Eliminate Split Placeholder Positions  
When splits create positions with unknown asset IDs (`{market_id}_split_YES`), try harder to resolve real asset IDs from the DB or defer position creation until a trade reveals the asset mapping.

### Fix 4: total_sold Counter Bug
Change `pos.total_sold += event.size` to `pos.total_sold += sell_size` in `_handle_sell` (cosmetic, doesn't affect PnL).

---

## Appendix: Diagnostic Scripts

- `investigate_gap.py` — Full diagnostic with market breakdowns
- `investigate_gap2.py` — Cash flow analysis and open position analysis
