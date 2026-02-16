# Optimization Plan: AvgCostBasisCalculator Performance + PnL Consistency

## Diagnosis Summary

Profile target: `GET /api/wallets/7/stats/?period=1M` (wallet has 15,151 trades and 2,271 activities)

Measured with `profile_perf.py` (5 runs):
- Fetch trades from DB: avg **0.2646s** (min 0.2537s, max 0.2734s)
- Fetch activities from DB: avg **0.0334s** (min 0.0328s, max 0.0344s)
- Avg cost replay simulation: avg **0.4864s** (min 0.4613s, max 0.5141s)
- Full `/api/wallets/7/stats/` response: avg **0.5819s** (min 0.4837s, max 0.8673s)

Result: replay is the dominant cost, and it is re-run on every request.

## Frontend + Endpoint Findings

Files checked:
- `frontend/js/app.js`
- `frontend/js/api.js`
- `frontend/index.html`
- `wallet_analysis/views.py`
- `wallet_analysis/serializers.py`
- `wallet_analysis/tasks.py`

What frontend calls:
- Wallet detail view uses `GET /api/wallets/{id}/stats/` for detailed PnL (`walletStats.wallet.realized_pnl`, `period_pnl`, charts).
- Dashboard and wallet card/list views use `GET /api/dashboard/` and `GET /api/wallets/`, which render `wallet.realized_pnl` from serializer field `subgraph_realized_pnl`.

Inconsistency leak:
- `WalletViewSet.stats` uses `AvgCostBasisCalculator` and writes result back to `wallet.subgraph_realized_pnl`.
- Background refresh task (`fetch_wallet_data`) updates `wallet.subgraph_realized_pnl` using `calculate_wallet_pnl(...)`, which currently resolves to `CostBasisPnLCalculator` (WACB path).
- Therefore dashboard/list can show stale or method-mismatched values until wallet stats is requested.

Dashboard endpoint behavior:
- `GET /api/dashboard/` does **not** run either calculator directly.
- It returns wallet summaries; PnL there comes from cached wallet field (`subgraph_realized_pnl`).

## Proposed Fixes (with effort + impact)

1. Add replay-result cache on `AnalysisRun` (JSON) with count-based invalidation
- Change: store per-period `AvgCostBasisCalculator` output in latest `AnalysisRun` row, with `trade_count` + `activity_count` snapshot.
- Invalidation: if current counts differ from cached counts, recompute and overwrite cache.
- Effort: **Medium** (model + migration + view logic).
- Impact: **High** on repeated wallet stats requests (eliminates replay on cache hits).

2. Unify PnL source in data refresh path
- Change: in `fetch_wallet_data`, compute wallet cached PnL using `AvgCostBasisCalculator(period='ALL')` instead of `calculate_wallet_pnl` default path.
- Effort: **Low**.
- Impact: **High** for consistency across dashboard, wallet list, and wallet detail.

3. Ensure all endpoints use same canonical realized PnL
- Change: keep `wallet.subgraph_realized_pnl` synchronized from avg-cost path only; dashboard/list continue to read this field.
- Effort: **Low**.
- Impact: **High** consistency; removes old calculator leakage.

4. Optional next step: incremental replay by timestamp
- Change: persist per-position state + last processed event timestamp, replay only new events.
- Effort: **High** (new persistence model, reconciliation rules, edge-case handling for corrections/backfills).
- Impact: **Very High** for large wallets, but not required for quick win.

## Quick Wins To Implement Now

- [ ] Switch refresh/task PnL write path to `AvgCostBasisCalculator`.
- [ ] Add `AnalysisRun` JSON cache fields + invalidation by trade/activity counts.
- [ ] Use cache in `wallets/{id}/stats/`.
- [ ] Keep dashboard/list and wallet detail values aligned via same avg-cost source.
