"""
Diagnose PnL overcounting for 1pixel wallet.

Loads data from Django DB and traces where the cost_basis calculator
overcounts relative to Polymarket's official PnL ($4,172.75 all-time).

Our cost_basis: $11,377 (2.7x overcounting)
Our cash_flow:  $11,776

This script identifies the specific double-counting patterns.
"""

import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
django.setup()

from decimal import Decimal
from collections import defaultdict
from wallet_analysis.models import Wallet, Trade, Activity, Market
from wallet_analysis.calculators.position_tracker import PositionTracker, ZERO


WALLET_ID = 7  # 1pixel
OFFICIAL_PNL = Decimal('4172.75')


def load_data():
    """Load 1pixel wallet data from DB."""
    wallet = Wallet.objects.get(id=WALLET_ID)
    trades = list(wallet.trades.select_related('market').order_by('timestamp'))
    activities = list(wallet.activities.select_related('market').order_by('timestamp'))
    return wallet, trades, activities


def summarize_data(trades, activities):
    """Print data summary."""
    print("=" * 80)
    print("DATA SUMMARY")
    print("=" * 80)
    print(f"Total trades: {len(trades)}")

    buys = [t for t in trades if t.side == 'BUY']
    sells = [t for t in trades if t.side == 'SELL']
    print(f"  BUYs: {len(buys)} totaling ${sum(Decimal(str(t.total_value)) for t in buys):.2f}")
    print(f"  SELLs: {len(sells)} totaling ${sum(Decimal(str(t.total_value)) for t in sells):.2f}")

    print(f"\nTotal activities: {len(activities)}")
    by_type = defaultdict(list)
    for a in activities:
        by_type[a.activity_type].append(a)

    for atype, items in sorted(by_type.items()):
        total_usdc = sum(Decimal(str(a.usdc_size)) for a in items)
        total_size = sum(Decimal(str(a.size)) for a in items)
        print(f"  {atype}: {len(items)} items, usdc_total=${total_usdc:.2f}, size_total={total_size:.2f}")

    # Cash flow PnL (simple)
    buy_cost = sum(Decimal(str(t.total_value)) for t in buys)
    sell_rev = sum(Decimal(str(t.total_value)) for t in sells)
    redeem_rev = sum(Decimal(str(a.usdc_size)) for a in by_type.get('REDEEM', []))
    merge_rev = sum(Decimal(str(a.usdc_size)) for a in by_type.get('MERGE', []))
    split_cost = sum(Decimal(str(a.usdc_size)) for a in by_type.get('SPLIT', []))
    reward_rev = sum(Decimal(str(a.usdc_size)) for a in by_type.get('REWARD', []))
    conversion_rev = sum(Decimal(str(a.usdc_size)) for a in by_type.get('CONVERSION', []))

    inflows = sell_rev + redeem_rev + merge_rev + reward_rev + conversion_rev
    outflows = buy_cost + split_cost
    cash_flow_pnl = inflows - outflows

    print(f"\nCASH FLOW PnL BREAKDOWN:")
    print(f"  Buy cost:       ${buy_cost:.2f}")
    print(f"  Sell revenue:   ${sell_rev:.2f}")
    print(f"  Redeem revenue: ${redeem_rev:.2f}")
    print(f"  Merge revenue:  ${merge_rev:.2f}")
    print(f"  Split cost:     ${split_cost:.2f}")
    print(f"  Reward revenue: ${reward_rev:.2f}")
    print(f"  Conversion rev: ${conversion_rev:.2f}")
    print(f"  --")
    print(f"  Cash flow PnL:  ${cash_flow_pnl:.2f}")
    print(f"  Official PnL:   ${OFFICIAL_PNL:.2f}")
    print(f"  Overcounting:   ${cash_flow_pnl - OFFICIAL_PNL:.2f} ({float(cash_flow_pnl / OFFICIAL_PNL):.2f}x)")


def run_cost_basis_and_trace(trades, activities):
    """Run the cost basis tracker and trace per-event PnL."""
    print("\n" + "=" * 80)
    print("COST BASIS TRACKER ANALYSIS")
    print("=" * 80)

    # Build market resolutions
    market_ids = set()
    for a in activities:
        mid = getattr(a, 'market_id', None)
        if mid:
            market_ids.add(mid)
    resolutions = {}
    if market_ids:
        resolved = Market.objects.filter(id__in=market_ids, resolved=True).exclude(winning_outcome='')
        resolutions = {str(m.id): m.winning_outcome for m in resolved}

    tracker = PositionTracker()
    positions, realized_events = tracker.process_events(trades, activities, resolutions)

    total_realized = sum(e.amount for e in realized_events)
    print(f"\nCost basis total realized PnL: ${total_realized:.2f}")
    print(f"Official PnL:                  ${OFFICIAL_PNL:.2f}")
    print(f"Overcounting:                  ${total_realized - OFFICIAL_PNL:.2f} ({float(total_realized / OFFICIAL_PNL):.2f}x)")
    print(f"Total realized events: {len(realized_events)}")

    return positions, realized_events


def analyze_market_overlap(trades, activities, realized_events):
    """
    KEY DIAGNOSTIC: Find markets where BOTH sells AND redeems generate PnL.

    Hypothesis: For resolved markets, the wallet:
    1. Buys YES tokens at $0.60
    2. Sometimes sells some before resolution (SELL events -> realized PnL)
    3. Market resolves -> REDEEM events (-> realized PnL on remaining position)

    This is NOT double-counting if the position tracker correctly reduces quantity
    on sells before computing redeem PnL. BUT if sells reduce position AND redeems
    also claim full size, that's overcounting.
    """
    print("\n" + "=" * 80)
    print("MARKET OVERLAP ANALYSIS: Markets with BOTH sells AND redeems")
    print("=" * 80)

    # Group trades by market
    trades_by_market = defaultdict(list)
    for t in trades:
        mid = getattr(t, 'market_id', None)
        if mid:
            trades_by_market[str(mid)].append(t)

    # Group activities by market
    activities_by_market = defaultdict(lambda: defaultdict(list))
    for a in activities:
        mid = getattr(a, 'market_id', None)
        if mid:
            activities_by_market[str(mid)][a.activity_type].append(a)

    # Group realized events by market
    events_by_market = defaultdict(list)
    for e in realized_events:
        if e.market_id:
            events_by_market[str(e.market_id)].append(e)

    # Find markets with both sells AND redeems
    overlap_markets = []
    for mid in set(list(trades_by_market.keys()) + list(activities_by_market.keys())):
        market_trades = trades_by_market.get(mid, [])
        market_activities = activities_by_market.get(mid, {})
        sells = [t for t in market_trades if t.side == 'SELL']
        redeems = market_activities.get('REDEEM', [])

        if sells and redeems:
            sell_value = sum(Decimal(str(t.total_value)) for t in sells)
            redeem_value = sum(Decimal(str(a.usdc_size)) for a in redeems)
            market_events = events_by_market.get(mid, [])
            total_pnl = sum(e.amount for e in market_events)
            overlap_markets.append({
                'market_id': mid,
                'sells': len(sells),
                'sell_value': sell_value,
                'redeems': len(redeems),
                'redeem_value': redeem_value,
                'realized_pnl': total_pnl,
            })

    overlap_markets.sort(key=lambda x: abs(x['realized_pnl']), reverse=True)
    total_overlap_pnl = sum(m['realized_pnl'] for m in overlap_markets)

    print(f"\nFound {len(overlap_markets)} markets with BOTH sells AND redeems")
    print(f"Total PnL from these markets: ${total_overlap_pnl:.2f}")
    print(f"\nTop 10 by absolute PnL:")
    for m in overlap_markets[:10]:
        title = ""
        try:
            market = Market.objects.get(id=m['market_id'])
            title = market.title[:50]
        except Market.DoesNotExist:
            pass
        print(f"  Market {m['market_id']}: PnL=${m['realized_pnl']:.2f}")
        print(f"    {title}")
        print(f"    Sells: {m['sells']} (${m['sell_value']:.2f}), Redeems: {m['redeems']} (${m['redeem_value']:.2f})")


def analyze_split_merge_phantom(trades, activities, positions):
    """
    Check if SPLITs create phantom positions that inflate PnL.

    SPLIT: Spend USDC -> get YES + NO tokens (at 50/50 cost basis)
    If only one side is later sold/redeemed and the other isn't tracked,
    the cost basis could be wrong.
    """
    print("\n" + "=" * 80)
    print("SPLIT/MERGE PHANTOM POSITION ANALYSIS")
    print("=" * 80)

    split_activities = [a for a in activities if a.activity_type == 'SPLIT']
    merge_activities = [a for a in activities if a.activity_type == 'MERGE']

    # Find markets with splits
    split_markets = set()
    for a in split_activities:
        mid = getattr(a, 'market_id', None)
        if mid:
            split_markets.add(str(mid))

    print(f"Markets with SPLITs: {len(split_markets)}")
    print(f"Total SPLITs: {len(split_activities)}")
    print(f"Total SPLIT USDC: ${sum(Decimal(str(a.usdc_size)) for a in split_activities):.2f}")
    print(f"Total MERGEs: {len(merge_activities)}")
    print(f"Total MERGE USDC: ${sum(Decimal(str(a.usdc_size)) for a in merge_activities):.2f}")

    # Check for phantom/orphan positions from splits
    phantom_count = 0
    phantom_pnl = ZERO
    for asset, pos in positions.items():
        if '_split_' in asset:
            phantom_count += 1
            phantom_pnl += pos.realized_pnl
            if pos.realized_pnl != ZERO or pos.quantity != ZERO:
                print(f"  Phantom position: {asset}")
                print(f"    qty={pos.quantity}, avg_price={pos.avg_price}, realized_pnl={pos.realized_pnl}")

    print(f"\nPhantom split positions: {phantom_count}, PnL from phantoms: ${phantom_pnl:.2f}")


def analyze_redeem_asset_resolution(trades, activities):
    """
    Check how many REDEEMs have empty asset fields and how resolution works.

    If asset resolution fails, redeems may create NEW positions instead of
    closing existing ones, leading to incorrect cost basis.
    """
    print("\n" + "=" * 80)
    print("REDEEM ASSET RESOLUTION ANALYSIS")
    print("=" * 80)

    redeems = [a for a in activities if a.activity_type == 'REDEEM']
    with_asset = [a for a in redeems if a.asset]
    without_asset = [a for a in redeems if not a.asset]

    print(f"Total REDEEMs: {len(redeems)}")
    print(f"  With asset field: {len(with_asset)}")
    print(f"  Without asset field: {len(without_asset)} (need resolution)")

    # For redeems without asset, check if they can be resolved
    # via market_assets map or position inference
    winner_redeems = [a for a in redeems if Decimal(str(a.usdc_size)) > ZERO]
    loser_redeems = [a for a in redeems if Decimal(str(a.usdc_size)) == ZERO]
    print(f"\n  Winner REDEEMs (usdc > 0): {len(winner_redeems)}")
    print(f"    Total USDC: ${sum(Decimal(str(a.usdc_size)) for a in winner_redeems):.2f}")
    print(f"  Loser REDEEMs (usdc = 0): {len(loser_redeems)}")

    # Check resolution: redeems without asset AND without outcome
    no_resolution_data = [a for a in redeems if not a.asset and not a.outcome]
    print(f"  REDEEMs with neither asset nor outcome: {len(no_resolution_data)}")


def deep_trace_single_market(trades, activities, market_id):
    """Trace a single market's events step-by-step through the position tracker."""
    print(f"\n{'=' * 80}")
    print(f"DEEP TRACE: Market {market_id}")
    print("=" * 80)

    try:
        market = Market.objects.get(id=market_id)
        print(f"Title: {market.title}")
        print(f"Resolved: {market.resolved}, Winning: {market.winning_outcome}")
    except Market.DoesNotExist:
        print("(Market not found in DB)")

    # Filter to this market
    market_trades = [t for t in trades if str(getattr(t, 'market_id', '')) == str(market_id)]
    market_activities = [a for a in activities if str(getattr(a, 'market_id', '')) == str(market_id)]

    print(f"\nTrades: {len(market_trades)}")
    for t in sorted(market_trades, key=lambda x: x.timestamp):
        print(f"  [{t.datetime}] {t.side} {t.size} @ ${t.price} = ${t.total_value} (asset={t.asset[:16]}... outcome={t.outcome})")

    print(f"\nActivities: {len(market_activities)}")
    for a in sorted(market_activities, key=lambda x: x.timestamp):
        print(f"  [{a.datetime}] {a.activity_type} size={a.size} usdc=${a.usdc_size} (asset={a.asset[:16] if a.asset else 'EMPTY'} outcome={a.outcome or 'EMPTY'})")

    # Run tracker on just this market's data
    resolutions = {}
    try:
        m = Market.objects.get(id=market_id)
        if m.resolved and m.winning_outcome:
            resolutions[str(m.id)] = m.winning_outcome
    except Market.DoesNotExist:
        pass

    tracker = PositionTracker()
    positions, events = tracker.process_events(market_trades, market_activities, resolutions)

    print(f"\nPositions after processing:")
    for asset, pos in positions.items():
        print(f"  {asset[:20]}... outcome={pos.outcome}")
        print(f"    qty={pos.quantity:.4f}, avg_price={pos.avg_price:.6f}")
        print(f"    realized_pnl=${pos.realized_pnl:.4f}")
        print(f"    total_bought={pos.total_bought:.4f}, total_sold={pos.total_sold:.4f}")
        print(f"    total_cost=${pos.total_cost:.4f}, total_revenue=${pos.total_revenue:.4f}")

    print(f"\nRealized events: {len(events)}")
    total = ZERO
    for e in events:
        total += e.amount
        print(f"  [{e.datetime}] asset={e.asset[:20] if e.asset else 'NONE'}... amount=${e.amount:.4f} (cumulative=${total:.4f})")

    return total


def analyze_pnl_by_event_type(trades, activities):
    """
    Break down cost_basis PnL by the EVENT TYPE that generated it.

    This directly shows whether sells vs redeems vs merges are the source
    of overcounting.
    """
    print("\n" + "=" * 80)
    print("PNL BY EVENT TYPE (from cost basis tracker)")
    print("=" * 80)

    # Build market resolutions
    market_ids = set()
    for a in activities:
        mid = getattr(a, 'market_id', None)
        if mid:
            market_ids.add(mid)
    resolutions = {}
    if market_ids:
        resolved = Market.objects.filter(id__in=market_ids, resolved=True).exclude(winning_outcome='')
        resolutions = {str(m.id): m.winning_outcome for m in resolved}

    # We need to patch the tracker to tag events by type.
    # Instead, we'll re-run with instrumented tracking.
    from wallet_analysis.calculators.position_tracker import _Event, PositionState, RealizedPnLEvent

    tracker = PositionTracker()

    # Build events and process, but also categorize each realized event
    events = tracker._build_event_list(trades, activities)
    market_assets = tracker._build_market_assets_map(trades, activities)
    tracker._market_resolutions = resolutions

    positions = {}
    realized_events = []

    # Track which event type produced each realized PnL event
    pnl_by_type = defaultdict(Decimal)
    count_by_type = defaultdict(int)

    for event in events:
        pre_count = len(realized_events)
        tracker._process_event(event, positions, realized_events, market_assets)

        # Check if new realized events were generated
        new_events = realized_events[pre_count:]
        for re in new_events:
            pnl_by_type[event.event_type] += re.amount
            count_by_type[event.event_type] += 1

    print(f"\nRealized PnL breakdown by source event type:")
    total = ZERO
    for etype in ['SELL', 'REDEEM', 'MERGE', 'REWARD', 'CONVERSION']:
        pnl = pnl_by_type.get(etype, ZERO)
        count = count_by_type.get(etype, 0)
        total += pnl
        print(f"  {etype:12s}: ${pnl:>12.2f} ({count} events)")

    print(f"  {'TOTAL':12s}: ${total:>12.2f}")
    print(f"  {'OFFICIAL':12s}: ${OFFICIAL_PNL:>12.2f}")
    print(f"  {'EXCESS':12s}: ${total - OFFICIAL_PNL:>12.2f}")


def analyze_negative_quantity_positions(trades, activities):
    """
    Find positions where more was sold/redeemed than bought.

    This indicates the cost basis was wrong - selling from a zero-quantity position
    generates PnL using a stale or zero avg_price, which inflates profits.
    """
    print("\n" + "=" * 80)
    print("NEGATIVE/ZERO QUANTITY SELL ANALYSIS")
    print("=" * 80)

    market_ids = set()
    for a in activities:
        mid = getattr(a, 'market_id', None)
        if mid:
            market_ids.add(mid)
    resolutions = {}
    if market_ids:
        resolved = Market.objects.filter(id__in=market_ids, resolved=True).exclude(winning_outcome='')
        resolutions = {str(m.id): m.winning_outcome for m in resolved}

    tracker = PositionTracker()
    positions, _ = tracker.process_events(trades, activities, resolutions)

    # Find positions where total_sold > total_bought
    oversold = []
    for asset, pos in positions.items():
        if pos.total_sold > pos.total_bought and pos.total_bought > ZERO:
            oversold.append(pos)

    print(f"\nPositions where total_sold > total_bought: {len(oversold)}")
    for pos in sorted(oversold, key=lambda p: abs(p.realized_pnl), reverse=True)[:10]:
        print(f"  {pos.asset[:20]}... ({pos.outcome})")
        print(f"    bought={pos.total_bought:.2f}, sold={pos.total_sold:.2f}, excess={pos.total_sold - pos.total_bought:.2f}")
        print(f"    realized_pnl=${pos.realized_pnl:.2f}")


def analyze_same_tx_trades_and_redeems(trades, activities):
    """
    CRITICAL CHECK: Find cases where the same transaction hash appears
    in BOTH trades AND activities.

    If the Polymarket API returns the same event as both a TRADE (sell)
    and a REDEEM, that's direct double-counting.
    """
    print("\n" + "=" * 80)
    print("SAME TRANSACTION HASH OVERLAP CHECK")
    print("=" * 80)

    trade_txs = defaultdict(list)
    for t in trades:
        trade_txs[t.transaction_hash].append(t)

    activity_txs = defaultdict(list)
    for a in activities:
        activity_txs[a.transaction_hash].append(a)

    overlap_txs = set(trade_txs.keys()) & set(activity_txs.keys())
    print(f"\nUnique trade tx hashes: {len(trade_txs)}")
    print(f"Unique activity tx hashes: {len(activity_txs)}")
    print(f"Overlapping tx hashes: {len(overlap_txs)}")

    if overlap_txs:
        # Check specifically for SELL trades that overlap with REDEEMs
        sell_redeem_overlap = 0
        sell_redeem_overlap_value = ZERO
        for tx in overlap_txs:
            t_list = trade_txs[tx]
            a_list = activity_txs[tx]
            sells = [t for t in t_list if t.side == 'SELL']
            redeems = [a for a in a_list if a.activity_type == 'REDEEM']
            if sells and redeems:
                sell_redeem_overlap += 1
                sell_redeem_overlap_value += sum(Decimal(str(t.total_value)) for t in sells)

        print(f"  SELL+REDEEM in same tx: {sell_redeem_overlap} txs, sell_value=${sell_redeem_overlap_value:.2f}")

        # Show a few examples
        shown = 0
        for tx in sorted(overlap_txs)[:5]:
            t_list = trade_txs[tx]
            a_list = activity_txs[tx]
            print(f"\n  TX: {tx}")
            for t in t_list:
                print(f"    TRADE: {t.side} {t.size}@{t.price}=${t.total_value}")
            for a in a_list:
                print(f"    ACTIVITY: {a.activity_type} size={a.size} usdc=${a.usdc_size}")
            shown += 1


def find_worst_overcounted_market(trades, activities, realized_events):
    """
    Find the single market contributing most excess PnL and deep-trace it.
    """
    print("\n" + "=" * 80)
    print("FINDING WORST OVERCOUNTED MARKET FOR DEEP TRACE")
    print("=" * 80)

    # Group realized events by market
    events_by_market = defaultdict(Decimal)
    for e in realized_events:
        if e.market_id:
            events_by_market[str(e.market_id)] += e.amount

    # Sort by absolute PnL
    top_markets = sorted(events_by_market.items(), key=lambda x: abs(x[1]), reverse=True)

    print("\nTop 5 markets by absolute realized PnL:")
    for mid, pnl in top_markets[:5]:
        try:
            market = Market.objects.get(id=mid)
            title = market.title[:60]
        except Market.DoesNotExist:
            title = "(unknown)"
        print(f"  {mid}: ${pnl:.2f} - {title}")

    # Deep trace the top market
    if top_markets:
        top_mid = top_markets[0][0]
        deep_trace_single_market(trades, activities, top_mid)


def main():
    print("Loading 1pixel wallet data...")
    wallet, trades, activities = load_data()
    print(f"Wallet: {wallet.name or wallet.pseudonym} ({wallet.address})")

    summarize_data(trades, activities)

    positions, realized_events = run_cost_basis_and_trace(trades, activities)

    analyze_pnl_by_event_type(trades, activities)
    analyze_same_tx_trades_and_redeems(trades, activities)
    analyze_market_overlap(trades, activities, realized_events)
    analyze_split_merge_phantom(trades, activities, positions)
    analyze_redeem_asset_resolution(trades, activities)
    analyze_negative_quantity_positions(trades, activities)
    find_worst_overcounted_market(trades, activities, realized_events)


if __name__ == '__main__':
    main()
