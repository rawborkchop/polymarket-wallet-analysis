# Task: Audit DB schema, queries, and data flow for performance

## Goal
The app should respond in <1 second for any wallet, even with 50K+ trades. Currently it takes ~0.6s for 15K trades which is borderline. Audit everything and produce a plan.

## What to audit

### 1. Database Schema
- Read wallet_analysis/models.py
- Check all indexes — are they optimal for the queries we run?
- Check field types — any unnecessary overhead?
- Is the schema normalized correctly or over/under-normalized?
- Are there missing indexes for common query patterns?

### 2. Query Patterns
- Read wallet_analysis/calculators/pnl_calculator.py (AvgCostBasisCalculator.calculate method)
- Read wallet_analysis/views.py (stats endpoint, dashboard endpoint)
- Read wallet_analysis/services.py
- Read wallet_analysis/tasks.py
- Profile which queries are slow — use Django's connection.queries or explain
- Check for N+1 queries, unnecessary joins, missing select_related/prefetch_related

### 3. Data Import Flow
- Read src/api/polymarket_client.py — how is data fetched from Polymarket?
- Read wallet_analysis/tasks.py — how is data imported/refreshed?
- Are there bulk operations or is it one-by-one inserts?
- Any unnecessary re-processing on refresh?

### 4. Calculator Bottleneck
- The AvgCostBasisCalculator loads ALL trades + activities into Python and replays in a loop
- Could parts of this be done in SQL? (e.g., aggregate buys/sells per asset)
- Could we use materialized views or pre-computed tables?
- Could we store position state incrementally?

### 5. Caching Strategy
- Current: cache based on trade/activity counts
- Is this sufficient? What about time-based cache?
- Should we cache at the HTTP level too?

## Output
Write a comprehensive AUDIT_REPORT.md with:
1. Current schema analysis with specific issues found
2. Query analysis with timing for each major query
3. Specific bottlenecks identified
4. Ranked list of optimizations (effort vs impact)
5. Recommended architecture for handling 100K+ trades per wallet

Create profile scripts to measure actual timings. Do NOT modify any existing files.

Run: cd "C:\Users\bort\git repos\polymarket-wallet-analysis"
Django settings: polymarket_project.settings

When completely finished, run:
```
openclaw system event --text "Done: Full audit complete. See AUDIT_REPORT.md" --mode now
```
