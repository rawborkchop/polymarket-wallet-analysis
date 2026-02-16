# CashFlowCalculator Plan

## Goal

Replace the current dual-calculator approach (CashFlowPnLCalculator + CostBasisPnLCalculator) with a single, clean `CashFlowCalculator` that matches Polymarket's official PnL using the cash flow formula:

```
PnL = sell_revenue + redeem_revenue + merge_revenue + rewards - buy_cost - split_cost
```

This is what the existing `PnLCalculator` (aliased as `CashFlowPnLCalculator`) already does via `MarketAggregator`/`DailyAggregator`. The $937.27 gap is likely from **missing reward data**, not a formula error. The existing cash flow method is correct.

## Current State

| Component | Role |
|---|---|
| `PnLCalculator` (pnl_calculator.py) | Cash flow method — already implements the formula correctly |
| `CostBasisPnLCalculator` (cost_basis_calculator.py) | WACB method — default calculator, uses PositionTracker |
| `MarketAggregator` / `DailyAggregator` | Aggregate cash flows by market/day, compute PnL via `CashFlowEntry` |
| `CashFlowEntry` | Data class with `inflows` (sells+redeems+merges+rewards) - `outflows` (buys+splits) |
| `PositionTracker` | Per-asset WACB cost basis tracking |

**Key finding:** The existing `PnLCalculator` already implements the exact Polymarket formula. `CashFlowEntry.pnl` = `inflows - outflows` = `(sells + redeems + merges + rewards) - (buys + splits)`. Conversions are already excluded.

## The Gap ($937.27)

From `close_the_gap.py` analysis:
- V2 cash flow: $19,235.50
- + Rewards ($47.68): $19,283.18  
- Official: $20,172.77
- Remaining gap: $889.59

**Root cause hypothesis:** Missing reward/incentive data. The activity API may not return all historical rewards (liquidity mining, trading incentives). This is a **data completeness** issue, not a formula issue.

## Plan

### 1. New `CashFlowCalculator` class

Create `wallet_analysis/calculators/cashflow_calculator.py` — a streamlined version of the existing `PnLCalculator` with period support built in.

```python
class CashFlowCalculator(IPnLCalculator):
    """
    Cash flow PnL calculator matching Polymarket's official method.
    
    PnL = sell_revenue + redeem_revenue + merge_revenue + rewards
         - buy_cost - split_cost
    
    Conversions are EXCLUDED (token swaps, not cash flows).
    """
    
    def __init__(self, cash_flow_provider=None):
        self._provider = cash_flow_provider or DjangoCashFlowProvider()
    
    def calculate(self, wallet) -> Dict[str, Any]:
        """Full period PnL."""
        ...
    
    def calculate_filtered(self, wallet, start_date=None, end_date=None) -> Dict[str, Any]:
        """Date-range filtered PnL."""
        ...
    
    def calculate_for_period(self, wallet, period: str) -> Dict[str, Any]:
        """
        PnL for named period: '1D', '1W', '1M', 'ALL'.
        Converts period to start_date/end_date and delegates.
        """
        ...
```

### 2. Period filtering logic

```python
from datetime import date, timedelta

PERIOD_DELTAS = {
    '1D': timedelta(days=1),
    '1W': timedelta(weeks=1),
    '1M': timedelta(days=30),
}

def _resolve_period(period: str) -> tuple[date | None, date | None]:
    if period == 'ALL':
        return None, None
    delta = PERIOD_DELTAS.get(period)
    if not delta:
        raise ValueError(f"Unknown period: {period}")
    return date.today() - delta, date.today()
```

### 3. Reuse existing aggregators

No changes to `MarketAggregator`, `DailyAggregator`, or `CashFlowEntry`. They already implement the formula correctly. The new calculator just wraps them with cleaner period support.

### 4. Return format

```python
{
    'period': '1W',                    # requested period
    'total_pnl': float,               # the cash flow PnL number
    'daily_pnl': [...],               # daily breakdown with cumulative
    'pnl_by_market': [...],           # top 20 markets by |PnL|
    'totals': {
        'buys': float,
        'sells': float,
        'redeems': float,
        'merges': float,
        'splits': float,
        'rewards': float,
        'conversions': float,          # tracked but excluded from PnL
        'inflows': float,
        'outflows': float,
    },
}
```

### 5. Integration

- Add `calculate_for_period` to `IPnLCalculator` interface (with default implementation)
- Wire into views/services by replacing `calculate_wallet_pnl_cashflow()` convenience function
- The `CostBasisPnLCalculator` remains available for WACB comparison but is no longer default
- Update the `pnl_calculator.py` module-level functions:
  - `calculate_wallet_pnl()` → uses `CashFlowCalculator`
  - `calculate_wallet_pnl_filtered()` → uses `CashFlowCalculator.calculate_filtered()`

### 6. Deprecation

- `PnLCalculator` / `CashFlowPnLCalculator` → deprecated alias to `CashFlowCalculator`
- `CostBasisPnLCalculator` → kept as optional, no longer default

## Files to Create/Modify

| File | Action |
|---|---|
| `calculators/cashflow_calculator.py` | **CREATE** — new calculator class |
| `calculators/__init__.py` | MODIFY — export CashFlowCalculator |
| `calculators/interfaces.py` | MODIFY — add `calculate_for_period` to `IPnLCalculator` |
| `calculators/pnl_calculator.py` | MODIFY — update convenience functions to use new calculator |

## Files NOT Modified

- `aggregators.py` — already correct
- `position_tracker.py` — WACB engine, separate concern
- `cost_basis_calculator.py` — kept as optional alternative
- `models.py` — no changes needed

## Addressing the Gap

The $889.59 gap is a **data issue**, not a formula issue. Separate investigation needed:
1. Query Polymarket rewards API more thoroughly (pagination, date ranges)
2. Check if some reward types aren't captured by the activity endpoint
3. Consider fetching reward data from on-chain events directly

The calculator should be correct regardless — when we capture more rewards, the number will converge.

## Estimated Effort

~2 hours. Most logic already exists in `PnLCalculator` and aggregators. The new class is mostly a cleaner wrapper with `calculate_for_period()` added.
