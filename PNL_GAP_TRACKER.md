# PnL Gap Tracker — 1pixel wallet

**Wallet:** `0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c` (DB id=7)
**Official PnL:** $20,172.77 (Polymarket leaderboard, Feb 16 2026)
**Our best calc:** $19,283.18 (V3 cash flow + rewards)
**Gap:** ~$889.59 (4.4%)

## Data Stats
- 15,151 trades (of 15,158 in API — 7 missing, 0.05%)
- 2,271 activities (1,669 redeems, 279 splits, 43 merges, 26 rewards, 254 conversions)
- Date range: 2025-02-03 → 2026-02-15
- Volume: 772K shares (matches PM's 773K within 0.17%)

## Cash Flow Formula
```
V2 = sell + redeem + merge - buy - split = $19,235.50
V3 = V2 + rewards = $19,283.18
V3 + open positions ($20.29) = $19,303.47
```

## Hypotheses Tested

### ✅ FIXED — Volume calculation
- **Problem:** We used `sum(size × price)` (notional), PM uses `sum(size)` (shares)
- **Result:** Fixed in code. No PnL impact, just display.

### ✅ FIXED — Open position mark-to-market
- **Problem:** Open positions not valued in PnL
- **Result:** Added `open_position_value` field. Closes ~$20 of gap.

### ❌ DESCARTADO — Missing rewards
- **Hypothesis:** Only 26 rewards ($47.68), maybe more exist
- **Result:** API confirms exactly 26 rewards. Wallet active since Feb 2025 only. No missing data.

### ❌ DESCARTADO — Multiple wallets
- **Hypothesis:** Profile might aggregate multiple wallet addresses
- **Result:** API shows single proxyWallet. Ruled out.

### ❌ DESCARTADO — Subgraph PnL cross-reference
- **Hypothesis:** Query Goldsky subgraph for authoritative PnL
- **Result:** Subgraph deprecated (404). Dead end.

### ❌ DESCARTADO — Missing trades
- **Hypothesis:** $569K volume gap = missing trades
- **Result:** Volume gap was measurement difference (notional vs shares). We have 99.95% of trades.

### ❌ DESCARTADO — Conversions as PnL source
- **Hypothesis:** 254 conversions ($21,493) in 79 temperature markets explain gap
- **Result:** Neg-risk splits are net $0 by construction (winner cancels losers). No PnL contribution.

### ❌ DESCARTADO — Partial conversion fraction
- **Hypothesis:** Some % of conversion value counts as PnL
- **Result:** 4.14% would fit mathematically but no logical basis. Conversions are net-zero.

## Hypotheses Pending

### ✅ CONFIRMADO — Position-level avg cost basis
- **Hypothesis:** PM uses per-position `realizedPnl = shares × (sell_price - avg_cost)`, not cash flow
- **Result:** ALL-TIME: $20,121.57 vs PM's $20,172.77 (gap $51, 99.75% match). CONFIRMED as correct method.

### ✅ CONFIRMADO — Monthly window is ~31-32 days, not 30
- **Hypothesis:** PM "1 month" profile PnL uses a wider window than exactly 30 days
- **Result:** With cutoff Jan 15-16 instead of Jan 17, simulation gives $1,276.15 vs PM's $1,280 (gap $3.85). Massive redeems (~$1,650) from NYC temperature markets on Jan 16-17 fall right on the boundary. Leaderboard API ($710) uses a DIFFERENT calculation than the profile page ($1,280).

### ❌ DESCARTADO — Rounding/precision accumulation
- Subsumed by avg cost basis fix — remaining gaps are <$51 (all-time) and <$4 (monthly)

### ⚠️ Weekly PnL — no match
- **Result:** PM profile=$7.56, leaderboard=$0.04, our sim=$33.25 (7-9d windows). Large relative gap but tiny absolute numbers. Weekly has very low activity for this wallet so methodology differences dominate. Not worth pursuing further — all-time and monthly validation are sufficient.

## Implemented Fixes
1. ✅ Volume: `sum(size)` instead of `sum(size*price)` — 6 edits, 3 files
2. ✅ Mark-to-market: `open_position_value` field added to calculator output
3. ✅ Phase 1A: Oversold cap in position_tracker.py
4. ✅ Phase 1B: REDEEM resolution reordered
5. ✅ Phase 1C: Phantom splits eliminated
6. ✅ Phase 0: Import date fix (data_start/end from actual trades)

## Debug Scripts (to clean up later)
diagnose_volume_gap.py, gap_reconciliation.py, gap_investigation.py, avg_cost_pnl.py, check_positions_api.py, check_profile_api.py, check_profile_browser.py, fetch_all_positions.py, check_data_completeness.py, analyze_gap_detail.py, close_the_gap.py, try_mark_to_market.py, try_simple_pnl.py, compare_per_position.py, compare_polymarket.py, reverse_pm_pnl.py, check_1month.py, check_dates.py, fix_dates.py, recalc_pnl.py, check_pnl.py, check_subgraph.py, debug_redeem*.py, diagnose_pnl.py, find_api*.py, quick_check.py, reimport.py, diagnose_overcounting.py, investigate_gap.py
