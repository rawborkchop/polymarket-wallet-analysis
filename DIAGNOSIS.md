# PnL Overcounting Diagnosis: 1pixel Wallet

## Summary

| Metric | Value |
|--------|-------|
| Wallet | 1pixel (`0xbdcd...9c`), DB id=7 |
| Official Polymarket PnL (ALL TIME) | **$4,172.75** |
| Our cost_basis calculator | **$54,377** (13.0x overcounting) |
| Our cash_flow calculator | **$40,776** (9.8x overcounting) |
| Data | 15,151 trades, 2,271 activities |

**Both calculators are massively overcounting.** The original ticket underestimated
the magnitude because it looked at cached/stale values. Fresh calculation shows
cost_basis is 13x off and cash_flow is 9.8x off.

---

## Root Cause Analysis

### Bug #1 (CRITICAL): CONVERSIONs double-counted as pure inflows

**Impact: ~$21,493 of phantom revenue**

The wallet has **254 CONVERSION activities totaling $21,493.24 USDC**.

In the **cash flow calculator**, CONVERSIONs are treated as pure inflows:
```
inflows = sells + redeems + merges + rewards + conversions
```

But a CONVERSION is not free money — it's exchanging one token position for
another (e.g., converting YES tokens to a different outcome token). The USDC
amount represents the value of what was converted, not net profit. It should
be **net-zero** unless there's a cost basis difference.

The cost_basis tracker correctly handles this (returns $0 PnL for conversions),
but the cash_flow calculator counts $21,493 as pure profit.

### Bug #2 (CRITICAL): SPLITs not properly netted against subsequent SELLs

**Impact: ~$23,766 of missing cost deduction**

The wallet has **279 SPLITs totaling $23,766.17**. A SPLIT spends USDC to create
YES + NO token pairs. In the cash flow calculator, splits are correctly subtracted
as outflows. BUT the sells of those split-created tokens are ALSO counted as
inflows — which is correct for cash flow. The problem is the *scale*.

The cash flow method treats `sell_revenue + redeem_revenue` as the full
inflow side. But when a wallet does:
1. SPLIT $100 -> get YES + NO tokens
2. SELL YES for $55
3. SELL NO for $50

Cash flow says: outflow=$100, inflow=$105, PnL=$5. This is correct.

But if the wallet instead:
1. BUY YES for $60
2. SPLIT $100 -> get YES + NO tokens
3. SELL YES for $55 (selling split + bought tokens)
4. REDEEM YES for $1/share on remaining

The interactions between SPLIT-created and BUY-created positions become
conflated. The cost basis tracker tries to handle this but has its own issues
(see Bug #3).

### Bug #3 (CRITICAL): Phantom positions from SPLITs with unknown asset IDs

**Impact: Cost basis assigned at $0.50 instead of actual market price**

The diagnostic found **76 phantom split positions** (e.g., `10741_split_YES`,
`10741_split_NO`). These occur when SPLITs happen for markets where the tracker
doesn't know the asset IDs (because the market_assets map only has data from
trades/activities with asset fields).

The phantom positions get avg_price=$0.50 and are never linked to the real
positions. When the real tokens from those splits are later sold, the sells
reduce a different position (the one from BUYs) whose cost basis doesn't
reflect the split-acquired tokens. This creates **cost basis dilution** —
the BUY-based position appears smaller than it should be, so the SELL generates
more profit than it should.

### Bug #4 (MAJOR): REDEEMs have ZERO asset resolution data

**Impact: 1,669 REDEEMs, all with empty asset AND outcome fields**

Every single REDEEM in the database has `asset=''` and `outcome=''`. The
position tracker has a 3-stage fallback:

1. **market_assets lookup** — works if trades exist for that market with asset/outcome
2. **Position inference** — works if only one open position exists for the market
3. **Market resolution** — works if Market model has `winning_outcome` set

If all 3 fail, the REDEEM is **skipped** (returns without generating PnL).
413 out of 1,669 REDEEMs generated realized events (1,256 events from redeem
source), meaning ~400 were dropped. However, the ones that DO resolve may
resolve incorrectly if the position inference picks the wrong position.

### Bug #5 (MAJOR): Positions oversold — total_sold > total_bought

**Impact: 93 positions where more tokens were sold/redeemed than bought**

For example, one position shows `bought=752, sold=1077, excess=325` with
`realized_pnl=$680`. This means the tracker sold tokens that don't exist
in the position. The PnL calculation becomes:
```
pnl = (sell_price - avg_price) * size
```
When selling from a near-zero position, `size = min(event.size, pos.quantity)`
caps the sell to remaining quantity, but `pos.quantity` may already be at
zero from prior sells, making `sell_size = event.size` (the full sell amount)
when the `else` branch executes. This generates PnL using a stale avg_price
on tokens the tracker never recorded buying.

**Root cause**: SPLITs add tokens to the position (via market_assets match)
but sometimes the asset ID lookup resolves differently for splits vs trades,
creating parallel positions for the same tokens. The BUY-based position is
then undersized relative to actual sells+redeems.

---

## PnL Breakdown by Event Type

| Source | PnL | Events |
|--------|-----|--------|
| SELL | $27,120 | 3,718 |
| REDEEM | $26,053 | 1,256 |
| MERGE | $1,157 | 43 |
| REWARD | $48 | 26 |
| CONVERSION | $0 | 0 |
| **TOTAL** | **$54,377** | **5,043** |
| **OFFICIAL** | **$4,173** | — |

SELLs and REDEEMs each contribute roughly half the overcounting.

---

## Deep Trace Example: Market 8513

*"Will the highest temperature in Dallas be between 52-53F on January 19?"*

- 15 BUYs of YES tokens at $0.01-$0.82 (total $120.03)
- 1 BUY of NO tokens at $0.82 (total $102.50)
- 6 SELLs of YES tokens at $0.17-$0.997 (total $2,016.01)
- 1 REDEEM of $0 (loser NO position)

**Cost basis says: $1,895.99 PnL** from this single market.

But look at the math: the wallet spent $120 on YES tokens and sold them for
$2,016 — that's ~$1,896 profit. This looks correct for this market in isolation.
The question is whether the $120 cost properly accounts for split-acquired tokens.

The NO position ($102.50 cost, 125 shares at $0.82) was never sold or redeemed
(still shows qty=125 at end). The redeem at $0 was correctly attributed as a
loser. So this market appears correctly calculated.

**The overcounting is distributed across many markets**, not concentrated in
a few. With 661 markets having both sells AND redeems, the small errors
compound.

---

## Cash Flow Calculator — Why $40,776?

```
Buy cost:       $124,289
Sell revenue:    $79,828
Redeem revenue:  $83,618
Merge revenue:    $3,844
Split cost:      $23,766
Reward revenue:      $48
Conversion rev:  $21,493
─────────────────────────
Cash flow PnL:   $40,776
```

The cash flow method is fundamentally flawed for this wallet because:

1. **CONVERSIONs ($21,493)** treated as pure income — should be ~$0 net
2. **The cash flow method assumes all activity is captured** — if we're
   missing some BUYs or SPLITs (e.g., from pagination limits or data gaps),
   the outflows are understated and PnL is inflated

---

## Proposed Fix (DO NOT implement yet)

### Fix 1: CONVERSION handling
- Cash flow calc: Do NOT count conversions as inflows. A conversion exchanges
  tokens, it's not a cash event unless there's a USDC delta.
- Cost basis calc: Already handles this correctly (returns $0).

### Fix 2: SPLIT cost basis must link to actual asset positions
- When a SPLIT occurs, the tracker needs to look up the actual YES/NO asset
  IDs for that market. Currently it falls back to placeholder positions when
  asset IDs are unknown.
- Solution: Pre-build the market_assets map from ALL trades before processing
  events, and also use the Activity.asset field if available.

### Fix 3: REDEEM asset resolution needs enrichment
- All 1,669 REDEEMs have empty asset/outcome. This means the API doesn't
  provide this data for REDEEM activities.
- Solution: Enrich REDEEMs using market resolution data + the market_assets
  map to determine which asset is being redeemed (winner vs loser).
- The current 3-stage fallback is on the right track but stage 2 (position
  inference) can fail if both YES and NO positions are open.

### Fix 4: Validate position quantity before sell/redeem
- When selling more than the tracked quantity, cap the PnL calculation to
  the tracked quantity, not the full sell size.
- Lines 251-252 of position_tracker.py already attempt this but the logic
  has a bug: `min(event.size, pos.quantity) if pos.quantity > ZERO else event.size`
  — the `else event.size` branch generates PnL on a zero-quantity position.

### Fix 5: Investigate data completeness
- The wallet may have activity from before our data window that created
  positions we don't have BUYs for. If we're missing early BUYs, every
  SELL generates phantom PnL.
- Check `wallet.data_start_date` vs actual first trade date.
- Consider importing historical positions from the PnL subgraph as initial state.

### Fix 6: Cross-validate against Polymarket's method
- Polymarket likely uses a simpler method: sum of `realizedPnl` from their
  `/positions` endpoint per-position.
- We should fetch their per-position PnL and compare against our per-position
  PnL to find exactly which positions diverge.

---

## Next Steps

1. Run `diagnose_overcounting.py` to get the full output
2. Review CONVERSION activities — are they token swaps or actual cash events?
3. Fetch Polymarket's per-position PnL via their API and diff against ours
4. Fix the `else event.size` bug in position_tracker.py line 251
5. Implement the cost basis fixes in priority order: Fix 1 > Fix 4 > Fix 3 > Fix 2
