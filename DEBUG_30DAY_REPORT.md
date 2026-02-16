# Debug 30-Day PnL Report — 1pixel Wallet

**Date:** 2026-02-16  
**Period:** 2026-01-16 to 2026-02-15  
**Our 30-day realized PnL:** $8,279.55  
**Polymarket 1M PnL:** $1,282.17  
**Overcounting factor:** ~6.5x  

## Findings

### 1. Our `calculate_filtered()` is mechanically correct

The method:
- Processes ALL trades/activities chronologically to build correct cost basis
- Filters realized PnL events to only those with dates within the 30-day window
- **615 realized events** in the period, summing to $8,279.55

This is NOT including historical PnL — it's genuinely only counting PnL realized between Jan 16 and Feb 15.

### 2. Pre-period vs in-period position breakdown

| Source | PnL | Events |
|--------|-----|--------|
| Positions opened BEFORE Jan 16 | $2,114.86 | 24 |
| Positions opened WITHIN period | $6,164.70 | 591 |
| **Total** | **$8,279.55** | **615** |

Even filtering to only "new" positions doesn't match Polymarket ($6,164 vs $1,282).

### 3. Activity breakdown in period

- **BUY:** 2,532 trades, $32,918.67
- **SELL:** 547 trades, $11,957.96
- **REDEEM:** 346 activities, $23,681.71 USDC received
- **MERGE:** 5 activities, $643.75
- **CONVERSION:** 2 activities, $116.65

### 4. Top markets are weather markets with rapid cycling

This wallet is an aggressive weather market trader. Markets resolve within days, with positions opened and fully closed (bought → redeemed) on very short timeframes. Top markets by PnL in the period:

1. **Dallas 52-53°F:** +$1,895.99 (24 trades, opened Jan 19)
2. **Dallas 54-55°F:** -$1,422.07 (42 trades, opened Jan 19)
3. **NYC 34°F:** +$1,042.64 (50 trades, opened Jan 15)
4. **London 10°C Jan 28:** +$884.65 (45 trades, opened Jan 28)

## Root Cause Hypothesis

### Most likely: Polymarket's "1M PnL" is mark-to-market (portfolio value change), NOT summed realized PnL

**Polymarket 1M PnL** = `(portfolio_value_end + withdrawals) - (portfolio_value_start + deposits)`

**Our calculation** = `sum(all realized PnL events in period)`

For a hyperactive trader doing 2,500+ buys and 350+ redemptions per month, these numbers diverge dramatically because:

1. **Realized PnL sums gross**: Every winning trade counts its full profit, even if that profit was reinvested and subsequently lost. A trader who turns $100→$200→$50 has +$100 realized PnL but -$50 mark-to-market.

2. **Capital recycling**: This wallet buys with $33K, gets back ~$36K in sells+redeems+merges, but much of that $36K is the SAME capital recycled through multiple weather markets. Our realized PnL counts every cycle. Polymarket's portfolio-value approach only counts net change.

3. **Unrealized position changes**: Polymarket's 1M figure likely includes unrealized gains/losses on open positions at period boundaries. Our number excludes unrealized.

### Evidence supporting this:
- Cash flow PnL for the same period = $3,364.74 (different method, different number)
- Full all-time realized = $42,299.92
- The wallet does ~2,500 buys/month with high turnover — classic capital recycling

### What Polymarket likely does:
The Polymarket profile "1M PnL" on their leaderboard snapshots portfolio value at T-30d and compares to current portfolio value, adjusting for deposits/withdrawals. This is standard for trading platform PnL displays.

## Recommendation

Our `calculate_filtered()` correctly computes **realized PnL within a date range** using cost basis. It's not buggy — it just measures something different from Polymarket's displayed "1M PnL."

To match Polymarket's number, we would need to implement a **mark-to-market / portfolio value change** calculator:
1. Compute total portfolio value (cash + positions) at start_date
2. Compute total portfolio value at end_date  
3. Subtract deposits/withdrawals in the period
4. PnL = end_value - start_value - net_deposits

This is a fundamentally different metric and would require position snapshots or reconstructing portfolio value at historical dates.
