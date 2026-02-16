#!/usr/bin/env python
"""Inspect schema indexes and explain query plans for key wallet queries.

Usage:
  python profiling/profile_query_plans.py --wallet-id 7
"""

import argparse
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django  # noqa: E402
from django.db import connection  # noqa: E402


TABLES = [
    'wallet_analysis_wallet',
    'wallet_analysis_market',
    'wallet_analysis_trade',
    'wallet_analysis_activity',
    'wallet_analysis_analysisrun',
]


def explain(sql: str):
    with connection.cursor() as cursor:
        cursor.execute('EXPLAIN QUERY PLAN ' + sql)
        return cursor.fetchall()


def list_indexes(table_name: str):
    rows = []
    with connection.cursor() as cursor:
        cursor.execute(f'PRAGMA index_list({table_name})')
        index_rows = cursor.fetchall()
        for idx in index_rows:
            idx_name = idx[1]
            cursor.execute(f'PRAGMA index_info({idx_name})')
            cols = [col[2] for col in cursor.fetchall()]
            rows.append((idx_name, cols, idx))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wallet-id', type=int, default=0)
    args = parser.parse_args()

    django.setup()

    from wallet_analysis.models import Wallet

    wallet_qs = Wallet.objects.filter(trades__isnull=False).distinct().order_by('-id')
    wallet = wallet_qs.filter(id=args.wallet_id).first() if args.wallet_id else wallet_qs.first()
    if wallet is None:
        raise SystemExit('No wallet with trades found; load data first.')

    wid = wallet.id
    print(f'wallet_id={wid} address={wallet.address}')

    print('\nIndexes by table')
    for table in TABLES:
        print(f'\n[{table}]')
        for idx_name, cols, raw in list_indexes(table):
            print(f'- {idx_name}: columns={cols} raw={raw}')

    sample_market_ids = list(wallet.trades.exclude(market_id__isnull=True).values_list('market_id', flat=True).distinct()[:10])
    sample_ids_sql = ','.join(str(x) for x in sample_market_ids) if sample_market_ids else 'NULL'

    queries = {
        'trade_order_for_replay': f'SELECT * FROM wallet_analysis_trade WHERE wallet_id = {wid} ORDER BY timestamp, id',
        'activity_order_for_replay': f'SELECT * FROM wallet_analysis_activity WHERE wallet_id = {wid} ORDER BY timestamp, id',
        'distinct_markets': f'SELECT COUNT(*) FROM (SELECT DISTINCT market_id FROM wallet_analysis_trade WHERE wallet_id = {wid})',
        'merge_redeem_markets': (
            f"SELECT DISTINCT market_id FROM wallet_analysis_activity WHERE wallet_id={wid} "
            "AND activity_type IN ('MERGE','REDEEM') AND market_id IS NOT NULL"
        ),
        'buy_markets_overlap': (
            f"SELECT DISTINCT market_id FROM wallet_analysis_trade WHERE wallet_id={wid} AND side='BUY' "
            f"AND market_id IN ({sample_ids_sql})"
        ),
        'latest_analysis_run': (
            f'SELECT * FROM wallet_analysis_analysisrun WHERE wallet_id={wid} '
            'ORDER BY timestamp DESC LIMIT 1'
        ),
    }

    print('\nEXPLAIN QUERY PLAN output')
    for label, sql in queries.items():
        print(f'\n[{label}]')
        print(sql)
        for row in explain(sql):
            print(f'- {row}')


if __name__ == '__main__':
    main()
