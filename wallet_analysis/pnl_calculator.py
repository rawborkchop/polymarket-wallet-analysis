"""
P&L Calculator - Calculates real P&L from trades, redeems, merges and splits.

The subgraph's realized_pnl serves as validation for our calculations.

Approach: Track P&L per market based on cash flows
- BUY = money out (negative)
- SELL = money in (positive)
- REDEEM = money in (positive) - winning positions get $1/share
- MERGE = money in (returns $1 for Yes+No pair)
- SPLIT = money out (converts $1 to Yes+No pair)
- REWARD = money in (pure profit)

Net P&L = total_inflows - total_outflows
"""

from decimal import Decimal
from collections import defaultdict


def calculate_wallet_pnl(wallet):
    """
    Calculate accurate P&L for a wallet from its trades and activities.

    Strategy: Track by market and day
    - For each market: P&L = (sells + redeems + merges) - (buys + splits)
    - Daily P&L aggregates across all markets
    """
    from .models import Trade, Activity

    # Get all trades and activities ordered by timestamp
    trades = list(wallet.trades.select_related('market').order_by('timestamp'))
    activities = list(wallet.activities.select_related('market').order_by('timestamp'))

    # Track per-market cash flows
    market_flows = defaultdict(lambda: {
        'buys': Decimal('0'),      # Money spent on buys
        'sells': Decimal('0'),     # Money received from sells
        'redeems': Decimal('0'),   # Money received from redeems
        'merges': Decimal('0'),    # Money received from merges
        'splits': Decimal('0'),    # Money spent on splits
        'rewards': Decimal('0'),   # Rewards received
    })

    # Track daily cash flows for timeline
    daily_flows = defaultdict(lambda: {
        'buys': Decimal('0'),
        'sells': Decimal('0'),
        'redeems': Decimal('0'),
        'merges': Decimal('0'),
        'splits': Decimal('0'),
        'rewards': Decimal('0'),
        'volume': Decimal('0'),
        'trade_count': 0,
    })

    # Process trades
    for trade in trades:
        date = trade.datetime.date()
        market_id = trade.market_id or 'unknown'
        value = Decimal(str(trade.total_value))

        daily_flows[date]['volume'] += value
        daily_flows[date]['trade_count'] += 1

        if trade.side == 'BUY':
            market_flows[market_id]['buys'] += value
            daily_flows[date]['buys'] += value
        elif trade.side == 'SELL':
            market_flows[market_id]['sells'] += value
            daily_flows[date]['sells'] += value

    # Process activities
    for activity in activities:
        date = activity.datetime.date()
        market_id = activity.market_id or 'unknown'
        usdc = Decimal(str(activity.usdc_size))

        if activity.activity_type == 'REDEEM':
            market_flows[market_id]['redeems'] += usdc
            daily_flows[date]['redeems'] += usdc
        elif activity.activity_type == 'MERGE':
            market_flows[market_id]['merges'] += usdc
            daily_flows[date]['merges'] += usdc
        elif activity.activity_type == 'SPLIT':
            market_flows[market_id]['splits'] += usdc
            daily_flows[date]['splits'] += usdc
        elif activity.activity_type == 'REWARD':
            market_flows[market_id]['rewards'] += usdc
            daily_flows[date]['rewards'] += usdc

    # Calculate total P&L
    total_inflows = Decimal('0')
    total_outflows = Decimal('0')

    for market_id, flows in market_flows.items():
        total_inflows += flows['sells'] + flows['redeems'] + flows['merges'] + flows['rewards']
        total_outflows += flows['buys'] + flows['splits']

    total_realized_pnl = total_inflows - total_outflows

    # Calculate daily P&L with cumulative
    sorted_dates = sorted(daily_flows.keys())
    cumulative = Decimal('0')
    daily_pnl_list = []

    for date in sorted_dates:
        flows = daily_flows[date]
        day_inflows = flows['sells'] + flows['redeems'] + flows['merges'] + flows['rewards']
        day_outflows = flows['buys'] + flows['splits']
        day_pnl = day_inflows - day_outflows
        cumulative += day_pnl

        daily_pnl_list.append({
            'date': date,
            'daily_pnl': float(day_pnl),
            'cumulative_pnl': float(cumulative),
            'volume': float(flows['volume']),
            'trades': flows['trade_count'],
            'buys': float(flows['buys']),
            'sells': float(flows['sells']),
            'redeems': float(flows['redeems']),
            'merges': float(flows['merges']),
        })

    # Calculate P&L by market (top 10)
    pnl_by_market = []
    for market_id, flows in market_flows.items():
        inflows = flows['sells'] + flows['redeems'] + flows['merges'] + flows['rewards']
        outflows = flows['buys'] + flows['splits']
        net_pnl = inflows - outflows
        pnl_by_market.append({
            'market_id': market_id,
            'pnl': float(net_pnl),
            'buys': float(flows['buys']),
            'sells': float(flows['sells']),
            'redeems': float(flows['redeems']),
        })

    # Sort by absolute P&L
    pnl_by_market.sort(key=lambda x: abs(x['pnl']), reverse=True)

    # Validation against subgraph
    subgraph_pnl = float(wallet.subgraph_realized_pnl or 0)
    calculated_pnl = float(total_realized_pnl)
    difference = subgraph_pnl - calculated_pnl
    difference_pct = (difference / abs(subgraph_pnl) * 100) if subgraph_pnl != 0 else 0

    return {
        'total_realized_pnl': calculated_pnl,
        'daily_pnl': daily_pnl_list,
        'pnl_by_market': pnl_by_market[:20],
        'totals': {
            'total_buys': float(total_outflows),
            'total_sells_redeems': float(total_inflows),
        },
        'validation': {
            'subgraph_pnl': subgraph_pnl,
            'calculated_pnl': calculated_pnl,
            'difference': difference,
            'difference_percent': round(difference_pct, 2),
            'is_valid': abs(difference_pct) < 20,  # Within 20% is acceptable given data limitations
            'note': 'Difference may be due to incomplete trade history or timing differences'
        }
    }


def calculate_wallet_pnl_filtered(wallet, start_date=None, end_date=None):
    """
    Calculate P&L for a specific date range.

    Note: This calculates P&L from the start, then filters display.
    The cumulative starts from the beginning of available data.
    """
    full_result = calculate_wallet_pnl(wallet)

    if not start_date and not end_date:
        return full_result

    # Filter daily_pnl by date range
    filtered_daily = []
    for entry in full_result['daily_pnl']:
        date = entry['date']
        if start_date and date < start_date:
            continue
        if end_date and date > end_date:
            continue
        filtered_daily.append(entry)

    # Recalculate cumulative for filtered range
    cumulative = Decimal('0')
    for entry in filtered_daily:
        cumulative += Decimal(str(entry['daily_pnl']))
        entry['cumulative_pnl'] = float(cumulative)

    return {
        **full_result,
        'daily_pnl': filtered_daily,
        'filtered_range': {
            'start': str(start_date) if start_date else None,
            'end': str(end_date) if end_date else None,
        }
    }
