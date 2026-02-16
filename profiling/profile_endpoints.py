#!/usr/bin/env python
"""Profile wallet stats/dashboard endpoints and avg-cost calculator timings.

Usage:
  python profiling/profile_endpoints.py --wallet-id 7 --runs 3
"""

import argparse
import os
import sys
import time
from statistics import mean

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django  # noqa: E402
from django.db import connection, reset_queries  # noqa: E402
from rest_framework.test import APIRequestFactory  # noqa: E402


def _ms(seconds: float) -> float:
    return round(seconds * 1000.0, 2)


def timed(label, fn, runs=3):
    durations = []
    query_counts = []
    for _ in range(runs):
        reset_queries()
        t0 = time.perf_counter()
        fn()
        durations.append(time.perf_counter() - t0)
        query_counts.append(len(connection.queries))

    return {
        'label': label,
        'avg_ms': _ms(mean(durations)),
        'min_ms': _ms(min(durations)),
        'max_ms': _ms(max(durations)),
        'query_counts': query_counts,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wallet-id', type=int, default=None)
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()

    django.setup()

    from wallet_analysis.models import Wallet
    from wallet_analysis.views import WalletViewSet, DashboardView
    from wallet_analysis.calculators.pnl_calculator import AvgCostBasisCalculator

    wallet_qs = Wallet.objects.filter(trades__isnull=False).distinct().order_by('-id')
    wallet = wallet_qs.filter(id=args.wallet_id).first() if args.wallet_id else wallet_qs.first()
    if wallet is None:
        raise SystemExit('No wallet with trades found; load data first.')

    print(f'wallet_id={wallet.id} address={wallet.address}')
    print(f'trades={wallet.trades.count()} activities={wallet.activities.count()}')

    stats_view = WalletViewSet.as_view({'get': 'stats'})
    dashboard_view = DashboardView.as_view()
    factory = APIRequestFactory()

    # Force one cold run for 1W cache path by clearing only that key.
    latest = wallet.analysis_runs.order_by('-timestamp').first()
    if latest and isinstance(latest.avg_cost_cache, dict) and '1W' in latest.avg_cost_cache:
        latest.avg_cost_cache.pop('1W', None)
        latest.save(update_fields=['avg_cost_cache'])

    results = []
    results.append(timed('stats(period=1W, cold-cache)', lambda: stats_view(factory.get(f'/api/wallets/{wallet.id}/stats/?period=1W'), pk=wallet.id), runs=1))
    results.append(timed('stats(period=1W, warm-cache)', lambda: stats_view(factory.get(f'/api/wallets/{wallet.id}/stats/?period=1W'), pk=wallet.id), runs=args.runs))
    results.append(timed('stats(period=ALL)', lambda: stats_view(factory.get(f'/api/wallets/{wallet.id}/stats/?period=ALL'), pk=wallet.id), runs=args.runs))
    results.append(timed('dashboard', lambda: dashboard_view(factory.get('/api/dashboard/')), runs=args.runs))
    results.append(timed('avg_cost.calculate(ALL)', lambda: AvgCostBasisCalculator(wallet.id).calculate(period='ALL'), runs=max(1, min(args.runs, 3))))
    results.append(timed('avg_cost.calculate(1M)', lambda: AvgCostBasisCalculator(wallet.id).calculate(period='1M'), runs=max(1, min(args.runs, 3))))

    print('\nTiming summary')
    for row in results:
        print(
            f"- {row['label']}: avg={row['avg_ms']}ms min={row['min_ms']}ms "
            f"max={row['max_ms']}ms queries={row['query_counts']}"
        )


if __name__ == '__main__':
    main()
