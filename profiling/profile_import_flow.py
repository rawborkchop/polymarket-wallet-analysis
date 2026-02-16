#!/usr/bin/env python
"""Profile data import path without writing to DB.

Measures:
- API fetch latency from Polymarket /activity pagination
- in-memory DTO conversion and cash-flow aggregation in TradeService

Usage:
  python profiling/profile_import_flow.py --wallet-address 0x... --days 30
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, UTC

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django  # noqa: E402


def ms(sec: float) -> float:
    return round(sec * 1000.0, 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wallet-address', required=True)
    parser.add_argument('--days', type=int, default=30)
    args = parser.parse_args()

    django.setup()

    from src.api.polymarket_client import PolymarketClient
    from src.services.trade_service import TradeService

    now = datetime.now(UTC)
    before_ts = int(now.timestamp())
    after_ts = int((now - timedelta(days=args.days)).timestamp())

    client = PolymarketClient()
    svc = TradeService(client)

    t0 = time.perf_counter()
    result = svc.get_all_activity(args.wallet_address, after_ts, before_ts)
    total_ms = ms(time.perf_counter() - t0)

    trades = result.get('trades', [])
    raw = result.get('raw_activity', {})
    counts = {k: len(v) for k, v in raw.items() if isinstance(v, list)}

    print(f'wallet={args.wallet_address} days={args.days}')
    print(f'total_elapsed_ms={total_ms}')
    print(f'trade_objects={len(trades)}')
    print('raw_activity_counts=' + str(counts))
    print('cash_flow=' + str(result.get('cash_flow', {})))


if __name__ == '__main__':
    main()
