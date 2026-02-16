import argparse
import os
import time
from statistics import mean

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')

import django

django.setup()

from django.test import Client
from wallet_analysis.models import Wallet, Trade, Activity
from wallet_analysis.calculators.pnl_calculator import AvgCostBasisCalculator


def _time_it(fn):
    t0 = time.perf_counter()
    result = fn()
    dt = time.perf_counter() - t0
    return dt, result


def run_once(wallet_id: int, period: str):
    wallet = Wallet.objects.get(pk=wallet_id)

    trades_time, trades = _time_it(
        lambda: list(
            Trade.objects.filter(wallet=wallet)
            .select_related('market')
            .order_by('timestamp', 'id')
        )
    )

    activities_time, activities = _time_it(
        lambda: list(
            Activity.objects.filter(wallet=wallet)
            .select_related('market')
            .order_by('timestamp', 'id')
        )
    )

    replay_time, pnl_result = _time_it(
        lambda: AvgCostBasisCalculator(wallet_id).calculate(period=period)
    )

    client = Client()
    endpoint = f'/api/wallets/{wallet_id}/stats/?period={period}'
    full_time, response = _time_it(lambda: client.get(endpoint))

    return {
        'trades_fetch_s': trades_time,
        'activities_fetch_s': activities_time,
        'replay_s': replay_time,
        'full_endpoint_s': full_time,
        'trade_count': len(trades),
        'activity_count': len(activities),
        'status_code': response.status_code,
        'total_pnl': pnl_result.get('total_pnl'),
        'period_pnl': pnl_result.get('period_pnl'),
    }


def main():
    parser = argparse.ArgumentParser(description='Profile wallet stats endpoint performance.')
    parser.add_argument('--wallet-id', type=int, default=7)
    parser.add_argument('--period', type=str, default='1M')
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()

    runs = []
    for _ in range(args.runs):
        runs.append(run_once(args.wallet_id, args.period.upper()))

    print(f'wallet_id={args.wallet_id} period={args.period.upper()} runs={args.runs}')
    print(f"trade_count={runs[0]['trade_count']} activity_count={runs[0]['activity_count']} status={runs[0]['status_code']}")

    for key in ('trades_fetch_s', 'activities_fetch_s', 'replay_s', 'full_endpoint_s'):
        values = [r[key] for r in runs]
        print(f"{key}: avg={mean(values):.4f}s min={min(values):.4f}s max={max(values):.4f}s")

    print(f"total_pnl={runs[-1]['total_pnl']} period_pnl={runs[-1]['period_pnl']}")


if __name__ == '__main__':
    main()
