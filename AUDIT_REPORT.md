# AUDIT_REPORT

## Scope and environment
- Date: 2026-02-16
- Code audited:
  - `wallet_analysis/models.py`
  - `wallet_analysis/calculators/pnl_calculator.py` (`AvgCostBasisCalculator.calculate`)
  - `wallet_analysis/views.py` (`stats`, `dashboard`)
  - `wallet_analysis/services.py`
  - `wallet_analysis/tasks.py`
  - `src/api/polymarket_client.py`
  - `src/services/trade_service.py`
- DB in this environment: SQLite (`db.sqlite3`), with WAL enabled.
- Profiled wallet: `id=7` (`0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c`)
- Profiled volume: `15,151` trades, `2,271` activities.

## Profiling scripts created
- `profiling/profile_endpoints.py`
- `profiling/profile_query_plans.py`
- `profiling/profile_import_flow.py`

## 1) Schema analysis

### Existing strengths
- Correct core FK/index coverage exists for replay paths:
  - `Trade(wallet_id, timestamp)`
  - `Activity(wallet_id, timestamp)`
- Unique constraints prevent duplicate ingest.
- `market` relation is normalized and reused across trades/activities.

### Specific schema/index issues
1. Missing index for "latest analysis run" query pattern.
- Query pattern in views: `AnalysisRun.objects.filter(wallet=...).order_by('-timestamp').first()`.
- Current index: only `analysisrun(wallet_id)`.
- `EXPLAIN` shows temp sort (`USE TEMP B-TREE FOR ORDER BY`).
- Recommendation: add composite index `(wallet_id, timestamp DESC)`.

2. Distinct-market and coverage checks lack purpose-built composite indexes.
- Patterns in stats:
  - `Trade` distinct on market for a wallet.
  - `Activity` distinct market for wallet + type in (`MERGE`,`REDEEM`).
  - `Trade` distinct market for wallet + `side='BUY'` and market IN set.
- Current queries rely on very wide unique indexes and temporary B-trees.
- Recommendation:
  - `Trade(wallet_id, market_id)`
  - `Trade(wallet_id, side, market_id)`
  - `Activity(wallet_id, activity_type, market_id)`

3. Wide uniqueness keys increase write and index-maintenance cost.
- `Trade` uniqueness currently includes many high-cardinality decimal/text fields.
- `Activity` uniqueness also includes decimal fields.
- This protects against duplicates but makes indexes large and expensive for bulk ingest.
- Recommendation: move to narrower natural keys (e.g., tx hash + log/index/event identity from source API if available).

4. Field-type overhead in hot path.
- Replay uses `Decimal` arithmetic for every event in Python.
- At 100K+ events this dominates CPU.
- Recommendation: keep persistence precision, but consider integer micro-units in precomputed tables/state and convert only at API boundary.

### Normalization assessment
- Overall normalization is reasonable.
- Not over-normalized for current needs.
- Main issue is not schema shape; it is repeated full-history replay and read-time recomputation.

## 2) Query analysis and timings

### Endpoint-level timings (measured)
From `profiling/profile_endpoints.py --wallet-id 7 --runs 3`:

| Operation | Avg time | Query count |
|---|---:|---:|
| `stats(period=1W, cold cache)` | 546.73 ms | 19 |
| `stats(period=1W, warm cache)` | 71.69 ms | 15 |
| `stats(period=ALL)` (warm) | 71.88 ms | 15 |
| `dashboard` | 32.47 ms | 12 |
| `AvgCostBasisCalculator.calculate('ALL')` | 434.69 ms | 3 |
| `AvgCostBasisCalculator.calculate('1M')` | 427.83 ms | 3 |

### Query-level observations
- Stats endpoint warm path still executes 15 queries.
- Two repeated `AnalysisRun` reads happen in one stats request (cache lookup + later metrics/copy data fetch).
- Stats endpoint performs a write on every read (`wallet.save(update_fields=['subgraph_realized_pnl', ...])`).
- Dashboard endpoint has N+1 behavior through serializer method fields:
  - For each top wallet, `trades.count()` and `distinct market count` are executed separately.

### Distinct + ordering inefficiency (important)
`Trade`/`Activity` models have default ordering by `-timestamp`. In some `distinct()` usages, this leaks into SQL and increases work.

Measured micro-benchmark:
- BUY market distinct with default ordering: ~14.75 ms
- BUY market distinct with `.order_by()` cleared: ~5.38 ms

This is a ~2.7x improvement for that query pattern.

### Replay data load timings
Measured separately:
- Load trades list for replay: ~279 ms
- Load activities list for replay: ~36 ms

These two reads are already most of the calculator runtime budget; then Python replay adds substantial CPU.

## 3) Data import flow analysis

### Current flow
- `PolymarketClient.fetch_all_activity` pages `/activity` backward in time, 500 rows/page.
- `TradeService.get_all_activity` converts rows and computes cash-flow preview in Python.
- `DatabaseService.save_trades/save_activities` bulk inserts in batches of 100 with `ignore_conflicts=True`.
- Task then recomputes full `AvgCostBasisCalculator(period='ALL')` and writes cache.

### Import timing measured
From `profiling/profile_import_flow.py --wallet-address ... --days 30`:
- End-to-end fetch+transform (no DB writes): ~1136.65 ms
- Returned: 2,749 trades + 338 redeems + 5 merges + 2 conversions.

### Import bottlenecks/risks
1. Full-history recompute after each refresh.
- Even a small incremental refresh triggers `AvgCostBasisCalculator('ALL')` replay.

2. Small DB batch size (`100`) for large imports.
- Increases transaction overhead and index churn.

3. Repeated market get/create checks.
- Cached per function call but still many DB lookups under large condition-id cardinality.

4. Backfill pass on activities executes extra read/update cycles.
- Useful for correctness, but should be bounded/incremental.

## 4) Calculator bottleneck analysis

### Current behavior
`AvgCostBasisCalculator.calculate`:
- Loads all trades + all activities into Python lists.
- Merges and sorts events.
- Replays full event history for every period request.

### Why this will fail <1s at 100K+
- Current ~434 ms at ~17.4K events (15,151 + 2,271).
- Rough linear extrapolation: ~2.5s to ~3.0s at 100K+ events (before extra endpoint overhead).
- Cold stats path then exceeds target significantly.

### SQL/offline opportunities
- SQL can pre-aggregate non-stateful components (counts, volumes, distinct markets, activity sums).
- Stateful avg-cost replay is harder in plain SQL; best solved with incremental position-state table + append-only processing.

## 5) Caching strategy analysis

### Current cache
- `avg_cost_cache` keyed by period on latest `AnalysisRun`.
- Validity tied only to `trade_count` and `activity_count`.

### Gaps
1. Count-only invalidation can miss edits/updates where counts do not change.
2. No TTL/versioning for stale cache protection.
3. Stats endpoint still does many non-cached queries and writes.
4. No HTTP-level caching for expensive read endpoints.

### Recommendations
- Cache key should include max timestamp/id fingerprints in addition to counts.
- Add TTL (`avg_cost_cache_updated_at` already exists; enforce max age).
- Add endpoint-level cache (`/wallets/{id}/stats?period=...`) with short TTL and explicit invalidation on successful ingest.

## 6) Ranked optimization plan (impact vs effort)

1. **Stop read-path writes + remove duplicate reads in stats endpoint**
- Impact: High
- Effort: Low
- Changes:
  - Do not update `wallet.subgraph_*` inside GET stats.
  - Reuse the first `latest_analysis` object instead of querying twice.

2. **Fix DISTINCT query shape and serializer N+1**
- Impact: High
- Effort: Low
- Changes:
  - Use `.order_by()` before `.distinct()` on market-id lists.
  - For dashboard top wallets: annotate `trade_count`, `unique_markets` once in queryset; remove per-wallet serializer method queries.

3. **Add composite indexes for hot filters/order**
- Impact: High
- Effort: Low-Medium
- Add:
  - `AnalysisRun(wallet_id, timestamp DESC)`
  - `Trade(wallet_id, market_id)`
  - `Trade(wallet_id, side, market_id)`
  - `Activity(wallet_id, activity_type, market_id)`

4. **Increase ingest batch sizes and reduce per-row market lookups**
- Impact: Medium-High
- Effort: Medium
- Changes:
  - Raise batch size (e.g., 500-2000, benchmarked).
  - Preload existing markets by condition_id for current payload chunk.

5. **Move avg-cost replay off synchronous request path**
- Impact: Very High
- Effort: Medium-High
- Changes:
  - Compute/update cache in Celery during ingest.
  - Stats endpoint should return cached values and never replay full history synchronously.

6. **Introduce incremental position state (event cursor model)**
- Impact: Very High (required for 100K+)
- Effort: High
- Changes:
  - Maintain per-wallet per-(market,outcome) running state table.
  - Process only new events since last cursor.
  - Persist daily/materialized aggregates for charts and market breakdown.

7. **Harden cache invalidation**
- Impact: Medium
- Effort: Medium
- Changes:
  - Replace count-only fingerprint with `(trade_count, activity_count, max_trade_ts, max_activity_ts, max_trade_id, max_activity_id)` or data-version counter.

## 7) Recommended architecture for 100K+ trades per wallet

### Target design
1. **Ingestion pipeline (async)**
- Fetch new activity window only.
- Upsert events.
- Append to an event-log table with stable sequence/cursor.

2. **Incremental state updater (async worker)**
- Reads unprocessed events per wallet.
- Updates:
  - `wallet_position_state` (size, avg_cost, realized_pnl per market/outcome)
  - `wallet_daily_pnl` (date bucket)
  - `wallet_market_pnl` (market aggregates)
- Stores last processed event cursor.

3. **Query layer (sync API)**
- `stats` and `dashboard` read precomputed tables only.
- No full replay and no write operations on GET.
- Add short HTTP cache (e.g., 15-60s) and cache bust on completed ingest.

4. **Database strategy**
- For 100K+ and concurrent workloads, prefer PostgreSQL over SQLite.
- Keep SQLite for local/dev only.

### Expected result
- Warm stats: typically <100 ms.
- Cold stats (no replay, precomputed reads): typically <300 ms.
- Scales to 100K+ trades without linear replay cost in request path.

## Key bottlenecks found (summary)
- Full-history avg-cost replay in request/refresh path.
- Stats endpoint doing unnecessary writes and redundant queries.
- Distinct queries paying extra cost due default ordering leakage.
- Dashboard serializer N+1 counts.
- Missing composite index for latest analysis lookup.

## Notes
- No existing project files were modified; only new profiling scripts and this report were added.
