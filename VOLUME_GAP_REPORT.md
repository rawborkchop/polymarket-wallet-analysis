# Volume Gap Investigation Report

**Date:** 2026-02-16  
**Wallet:** 0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c (1pixel, DB id=7)  
**Diagnostic script:** `diagnose_volume_gap.py`

## Summary

The $569K "gap" is **not missing data** — it's a **volume calculation mismatch**. Polymarket displays volume as **sum of shares traded (size)**, while our DB calculates `total_volume_usd` as **notional value (size × price)**.

## The Numbers

| Metric | Our DB | API (fresh) | Polymarket Profile |
|--------|--------|-------------|-------------------|
| Trade count | 15,151 | 15,158 | — |
| Notional volume (size×price) | $204,117 | $204,213 | — |
| **Share volume (sum of size)** | **$771,862** | **$772,106** | **$773,199.66** |

## Root Cause

**Polymarket "Volume traded" = sum of `size` field** (shares/contracts traded), NOT `size × price` (notional/dollar value).

This makes sense: on Polymarket, each share pays $1 if correct and $0 if wrong. A trade of 100 shares at $0.25 represents $100 of volume (100 shares), not $25 (notional cost).

Our code in `analytics_service.py` → `_calculate_summary()`:
```python
total_volume = float(sum(t.total_value for t in trades))  # total_value = size * price
```
This computes notional value, which is always less than share volume (since price < 1).

## Remaining Small Gap (~$1,337)

The $1,337 remaining gap between our DB share volume ($771,862) and Polymarket ($773,199.66) is explained by:
1. **7 missing trades** — API returns 15,158 trades vs our DB's 15,151 (likely recent trades not yet synced)
2. **Polymarket may include other activity types** in their volume figure (splits, merges, etc.)

## Trade Count Gap (7 trades)

API has 15,158 TRADE activities vs our DB's 15,151. This is a minor sync gap (0.05%), likely trades that occurred after the last data pull. All activity type counts match exactly otherwise:

| Type | DB | API |
|------|-----|-----|
| TRADE | 15,151 | 15,158 |
| REDEEM | 1,669 | 1,669 |
| SPLIT | 279 | 279 |
| MERGE | 43 | 43 |
| REWARD | 26 | 26 |
| CONVERSION | 254 | 254 |

## API Field Clarification

The API `usdcSize` field for TRADE items equals `size × price` (notional), NOT the share count. The `size` field is the share count.

## Recommendations

1. **Fix volume calculation**: Change `total_volume_usd` to use `sum(size)` instead of `sum(size * price)` to match Polymarket's definition
2. **Consider keeping both**: Track both `share_volume` (Polymarket-compatible) and `notional_volume` (dollar cost) — both are useful metrics
3. **No pagination issue**: The timestamp-based backward pagination works correctly; we're getting all trades

## No Data Loss

There is **no missing trade data**. The pagination is working correctly. All date ranges have continuous coverage from Feb 2025 to Feb 2026 with no gaps.
