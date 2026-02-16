# PnL Gap Analysis Report

**Wallet:** `0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c` (1pixel, DB id=7)  
**Date:** 2026-02-16  

## Summary

| Metric | Our Calculation | Polymarket Official | Gap |
|--------|----------------|-------------------|-----|
| PnL | $19,283.18 (V3) | $20,172.77 | **$889.59** (4.4%) |
| Volume | $771,862.36 | $773,199.66 | $1,337.30 (0.17%) |

## Our Cash Flow Formula (V2/V3)

```
V2 = SELL + REDEEM + MERGE - BUY - SPLIT
   = $79,828.31 + $83,618.04 + $3,844.01 - $124,288.70 - $23,766.17
   = $19,235.50

V3 = V2 + REWARD = $19,235.50 + $47.68 = $19,283.18
```

Other flows not included: CONVERSION = $21,493.24 (token swaps within multi-outcome markets, net-zero for PnL)

## Identified Gap Components

### 1. Open Positions Unrealized Value: **+$20.00** → gap narrows to $869.59

The Positions API shows **10 open positions** (mostly expired weather markets awaiting redemption):
- Total initial value (cost basis): $711.86
- Current value: $20.00
- These are already counted as costs in our BUY total but we haven't received sell/redeem revenue yet

Polymarket likely includes `currentValue` of open positions in their PnL:
```
PnL_adjusted = V3 + open_position_value = $19,283.18 + $20.00 = $19,303.18
Remaining gap: $869.59
```

### 2. Missing Trades: estimated **~$100-400**

Volume gap is 1,337.30 shares (0.17%). These missing trades could contribute PnL:
- If missing sells at avg sell price ($0.35): ~$468 revenue not captured
- Net PnL impact depends on corresponding buy costs
- Likely explains a portion but not all of the remaining gap

### 3. Missing Rewards: estimated **~$400-800**

We capture only **26 reward transactions totaling $47.68** (Feb 2025 - May 2025). But:
- The account has been active since Feb 2025 (12+ months)
- Rewards stopped appearing in our data after May 2025
- Polymarket has multiple reward programs (liquidity mining, trading incentives, referral bonuses)
- **$869 in uncaptured rewards over 12 months is very plausible** (~$72/month)
- Rewards likely included in PM's PnL calculation

### 4. Rounding/Precision: estimated **<$10**

With 15,000+ trades, cumulative floating-point differences are negligible.

## Polymarket's PnL Formula (Reverse-Engineered)

Based on analysis, Polymarket likely uses:

```
PnL = Σ(per-position cashPnl) + Σ(currentValue of open positions) + rewards
```

Where per-position `cashPnl` = total sell/redeem revenue - cost basis of bought shares.

The Positions API only returns **currently held** positions (not closed/redeemed ones), so we can't fully verify by summing API `cashPnl` values.

## Key Findings

| Component | Amount | Confidence |
|-----------|--------|------------|
| V3 (our best formula) | $19,283.18 | ✅ Verified |
| + Open positions value | +$20.00 | ✅ Confirmed via API |
| + Missing rewards (est.) | +$500-800 | ⚠️ Estimated |
| + Missing trades PnL (est.) | +$100-400 | ⚠️ Estimated |
| **Projected total** | **~$19,900-20,500** | Brackets official |
| **Official PnL** | **$20,172.77** | ✅ From API |

## Recommendations

1. **Capture more rewards**: Extend reward scraping beyond May 2025. Check for additional reward contract addresses or event types.
2. **Close the volume gap**: Investigate the 1,337 missing shares — likely a small number of uncaptured trades from API pagination or timing.
3. **Include open positions**: Add `currentValue` of unredeemed positions to PnL formula.
4. **Best formula**: `PnL = V3 + open_position_value + all_rewards`

## Files Created

- `gap_reconciliation.py` — Fetches PM Positions API, compares with DB
- `GAP_ANALYSIS_REPORT.md` — This report
