"""
Diagnostic script to investigate why PnL calculator overcounts by ~$22K for 1pixel.
"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
django.setup()

from decimal import Decimal
from collections import defaultdict
from wallet_analysis.models import Wallet, Trade, Activity, Market
from wallet_analysis.calculators.position_tracker import PositionTracker, ZERO

wallet = Wallet.objects.get(id=7)
print(f"Wallet: {wallet.name} ({wallet.address[:10]}...)")

trades = list(Trade.objects.filter(wallet=wallet).order_by('timestamp'))
activities = list(Activity.objects.filter(wallet=wallet).order_by('timestamp'))
print(f"Trades: {len(trades)}, Activities: {len(activities)}")

# Activity breakdown
act_counts = defaultdict(int)
for a in activities:
    act_counts[a.activity_type] += 1
print(f"Activity types: {dict(act_counts)}")

# Run the tracker
tracker = PositionTracker()
market_resolutions = {}
resolved_markets = Market.objects.filter(resolved=True).exclude(winning_outcome='')
for m in resolved_markets:
    market_resolutions[str(m.id)] = m.winning_outcome

db_market_assets = {}
rows = Trade.objects.filter(wallet=wallet).exclude(asset='').exclude(outcome='').values('market_id', 'outcome', 'asset').distinct()
for row in rows:
    mid = str(row['market_id'])
    if mid not in db_market_assets:
        db_market_assets[mid] = {}
    db_market_assets[mid][row['outcome']] = row['asset']

positions, realized_events = tracker.process_events(trades, activities, market_resolutions, db_market_assets=db_market_assets)

total_realized = sum(e.amount for e in realized_events)
print(f"\n=== TOTAL REALIZED PNL: ${total_realized:.2f} ===")

# ---- 1. Group realized PnL by source type ----
# We need to re-run but track event types. Instead, let's match events to their source.
# The realized_events don't carry event_type. Let's rebuild with tracking.

# Rebuild event list to match realized events to their source types
from wallet_analysis.calculators.position_tracker import _Event
type_order = {'BUY': 0, 'SPLIT': 1, 'SELL': 2, 'MERGE': 3, 'REDEEM': 4, 'REWARD': 5, 'CONVERSION': 6}

all_events = []
for t in trades:
    all_events.append(('TRADE', t.side, t.timestamp, t.asset, str(t.market_id), Decimal(str(t.total_value)), Decimal(str(t.size)), Decimal(str(t.price))))

for a in activities:
    all_events.append(('ACTIVITY', a.activity_type, a.timestamp, a.asset, str(a.market_id) if a.market_id else '', Decimal(str(a.usdc_size)), Decimal(str(a.size)), ZERO))

# Actually, let me just tag realized events by matching timestamps and inferring type
# Better approach: monkey-patch or just classify realized events by checking what activity/trade caused them

# Simple approach: for each realized event, check if there's a SELL trade or REDEEM/MERGE/CONVERSION activity at that timestamp+asset
sell_trades_by_ts = defaultdict(list)
for t in trades:
    if t.side == 'SELL':
        sell_trades_by_ts[(t.timestamp, t.asset or '')].append(t)

activity_by_ts = defaultdict(list)
for a in activities:
    activity_by_ts[a.timestamp].append(a)

# Classify realized events
pnl_by_type = defaultdict(Decimal)
events_by_type = defaultdict(list)

for re in realized_events:
    # Check if it's a sell
    key = (re.timestamp, re.asset)
    if key in sell_trades_by_ts:
        pnl_by_type['SELL'] += re.amount
        events_by_type['SELL'].append(re)
    elif re.timestamp in activity_by_ts:
        acts = activity_by_ts[re.timestamp]
        # Find matching activity type
        matched = False
        for a in acts:
            if a.activity_type in ('REDEEM', 'MERGE', 'CONVERSION', 'REWARD'):
                pnl_by_type[a.activity_type] += re.amount
                events_by_type[a.activity_type].append(re)
                matched = True
                break
        if not matched:
            pnl_by_type['UNKNOWN'] += re.amount
            events_by_type['UNKNOWN'].append(re)
    else:
        pnl_by_type['UNKNOWN'] += re.amount
        events_by_type['UNKNOWN'].append(re)

print("\n=== PNL BY EVENT TYPE ===")
for typ, pnl in sorted(pnl_by_type.items(), key=lambda x: -abs(x[1])):
    count = len(events_by_type[typ])
    print(f"  {typ}: ${pnl:.2f} ({count} events)")

# ---- 2. Markets with BOTH sell PnL AND redeem PnL ----
pnl_by_market_type = defaultdict(lambda: defaultdict(Decimal))
for re in realized_events:
    mid = re.market_id
    if not mid:
        continue
    # Classify
    key = (re.timestamp, re.asset)
    if key in sell_trades_by_ts:
        pnl_by_market_type[mid]['SELL'] += re.amount
    elif re.timestamp in activity_by_ts:
        for a in activity_by_ts[re.timestamp]:
            if a.activity_type in ('REDEEM', 'MERGE', 'CONVERSION', 'REWARD'):
                pnl_by_market_type[mid][a.activity_type] += re.amount
                break

print("\n=== MARKETS WITH BOTH SELL AND REDEEM PNL ===")
double_count_total = Decimal('0')
double_markets = []
for mid, types in pnl_by_market_type.items():
    if 'SELL' in types and 'REDEEM' in types:
        total = types['SELL'] + types['REDEEM']
        double_markets.append((mid, types['SELL'], types['REDEEM'], total))
        double_count_total += total

double_markets.sort(key=lambda x: -abs(x[3]))
for mid, sell_pnl, redeem_pnl, total in double_markets[:30]:
    try:
        market = Market.objects.get(id=mid)
        title = market.title[:60]
    except:
        title = "???"
    print(f"  Market {mid}: SELL=${sell_pnl:.2f} REDEEM=${redeem_pnl:.2f} TOTAL=${total:.2f} | {title}")

print(f"\n  Total PnL in double-counted markets: ${double_count_total:.2f}")
print(f"  Number of markets with both SELL+REDEEM: {len(double_markets)}")

# ---- 3. Positions where total_sold + redeemed > total_bought ----
print("\n=== POSITIONS WITH OVERSELLING (sold > bought without splits) ===")
oversold_count = 0
for asset, pos in positions.items():
    if pos.total_sold > pos.total_bought and pos.total_bought > ZERO:
        oversold_count += 1
        if oversold_count <= 10:
            print(f"  {pos.outcome} in market {pos.market_id}: bought={pos.total_bought:.2f} sold={pos.total_sold:.2f} diff={pos.total_sold - pos.total_bought:.2f}")
print(f"  Total oversold positions: {oversold_count}")

# ---- 4. Top 20 markets by PnL ----
market_pnl = defaultdict(Decimal)
market_cost = defaultdict(Decimal)
market_revenue = defaultdict(Decimal)
for asset, pos in positions.items():
    mid = pos.market_id
    if not mid:
        continue
    market_pnl[mid] += pos.realized_pnl
    market_cost[mid] += pos.total_cost
    market_revenue[mid] += pos.total_revenue

print("\n=== TOP 20 MARKETS BY ABSOLUTE PNL ===")
sorted_markets = sorted(market_pnl.items(), key=lambda x: -abs(x[1]))
for mid, pnl in sorted_markets[:20]:
    cost = market_cost[mid]
    revenue = market_revenue[mid]
    try:
        market = Market.objects.get(id=mid)
        title = market.title[:50]
        resolved = market.resolved
        winner = market.winning_outcome
    except:
        title = "???"
        resolved = False
        winner = ""
    print(f"  Market {mid}: PnL=${pnl:.2f} Cost=${cost:.2f} Rev=${revenue:.2f} Resolved={resolved} Winner={winner} | {title}")

# ---- 5. SPLIT analysis ----
print("\n=== SPLIT ANALYSIS ===")
split_activities = [a for a in activities if a.activity_type == 'SPLIT']
total_split_usdc = sum(Decimal(str(a.usdc_size)) for a in split_activities)
total_split_shares = sum(Decimal(str(a.size)) for a in split_activities)
print(f"  Total SPLITs: {len(split_activities)}")
print(f"  Total USDC spent on splits: ${total_split_usdc:.2f}")
print(f"  Total shares created per side: {total_split_shares:.2f}")

# Check if split tokens were then sold AND redeemed
split_market_ids = set(str(a.market_id) for a in split_activities if a.market_id)
print(f"  Markets with splits: {len(split_market_ids)}")

for mid in list(split_market_ids)[:10]:
    assets_in_market = {a: p for a, p in positions.items() if p.market_id == mid}
    try:
        market = Market.objects.get(id=mid)
        title = market.title[:50]
    except:
        title = "???"
    print(f"\n  Split market {mid}: {title}")
    for asset, pos in assets_in_market.items():
        print(f"    {pos.outcome}: bought={pos.total_bought:.2f} sold={pos.total_sold:.2f} qty={pos.quantity:.2f} avg={pos.avg_price:.4f} pnl=${pos.realized_pnl:.2f}")

# ---- 6. Check for duplicate activities (same tx_hash, same type) ----
print("\n=== DUPLICATE ACTIVITY CHECK ===")
act_keys = defaultdict(int)
for a in activities:
    key = (a.transaction_hash, a.activity_type, str(a.market_id), str(a.size), str(a.usdc_size))
    act_keys[key] += 1

dupes = {k: v for k, v in act_keys.items() if v > 1}
print(f"  Duplicate activity records: {len(dupes)}")
for k, v in list(dupes.items())[:5]:
    print(f"    {k[1]} tx={k[0][:20]}... market={k[2]} size={k[3]} usdc={k[4]} x{v}")

# ---- 7. REDEEM where we have NO position (phantom redeems) ----
print("\n=== REDEEM EVENTS ANALYSIS ===")
redeem_activities = [a for a in activities if a.activity_type == 'REDEEM']
total_redeem_usdc = sum(Decimal(str(a.usdc_size)) for a in redeem_activities)
print(f"  Total REDEEMs: {len(redeem_activities)}")
print(f"  Total USDC from redeems: ${total_redeem_usdc:.2f}")

# Count redeems with usdc > 0 (winners) vs usdc = 0 (losers)
winner_redeems = [a for a in redeem_activities if Decimal(str(a.usdc_size)) > 0]
loser_redeems = [a for a in redeem_activities if Decimal(str(a.usdc_size)) == 0]
print(f"  Winner redeems (usdc>0): {len(winner_redeems)}, total: ${sum(Decimal(str(a.usdc_size)) for a in winner_redeems):.2f}")
print(f"  Loser redeems (usdc=0): {len(loser_redeems)}")

# ---- 8. Key question: For markets with sells, are tokens being sold THEN also redeemed? ----
print("\n=== SELL-THEN-REDEEM DOUBLE COUNTING DEEP DIVE ===")
# For each market with both sell and redeem, check token flows
for mid, sell_pnl, redeem_pnl, total in double_markets[:10]:
    try:
        market = Market.objects.get(id=mid)
        title = market.title[:50]
    except:
        title = "???"
    
    # Get all trades for this market
    market_trades = [t for t in trades if str(t.market_id) == mid]
    market_acts = [a for a in activities if str(a.market_id) == mid]
    
    buys = [(t.outcome, Decimal(str(t.size)), Decimal(str(t.price))) for t in market_trades if t.side == 'BUY']
    sells = [(t.outcome, Decimal(str(t.size)), Decimal(str(t.price))) for t in market_trades if t.side == 'SELL']
    redeems = [(a.outcome, Decimal(str(a.size)), Decimal(str(a.usdc_size))) for a in market_acts if a.activity_type == 'REDEEM']
    splits = [(Decimal(str(a.size)), Decimal(str(a.usdc_size))) for a in market_acts if a.activity_type == 'SPLIT']
    
    total_bought = sum(s for _, s, _ in buys)
    total_sold = sum(s for _, s, _ in sells)
    total_redeemed = sum(s for _, s, _ in redeems)
    total_split = sum(s for s, _ in splits)
    
    print(f"\n  Market {mid}: {title}")
    print(f"    Bought: {total_bought:.2f} shares, Sold: {total_sold:.2f}, Redeemed: {total_redeemed:.2f}, Splits: {total_split:.2f}")
    print(f"    Net flow: bought({total_bought:.2f}) + splits({total_split:.2f}) - sold({total_sold:.2f}) - redeemed({total_redeemed:.2f}) = {total_bought + total_split - total_sold - total_redeemed:.2f}")
    print(f"    SELL PnL: ${sell_pnl:.2f}, REDEEM PnL: ${redeem_pnl:.2f}")
    
    # Per-outcome breakdown  
    for outcome in set(o for o, _, _ in buys + sells):
        ob = sum(s for o, s, _ in buys if o == outcome)
        os_ = sum(s for o, s, _ in sells if o == outcome)
        # Redeems don't have outcome usually, but check
        or_ = sum(s for o, s, _ in redeems if o == outcome)
        print(f"    {outcome}: bought={ob:.2f} sold={os_:.2f} redeemed_tagged={or_:.2f}")

# ---- 9. Summary ----
print("\n" + "="*60)
print("SUMMARY")
print("="*60)
print(f"Our calculated PnL: ${total_realized:.2f}")
print(f"Official Polymarket PnL: $20,173")
print(f"Gap: ${total_realized - Decimal('20173'):.2f}")
print(f"\nPnL by type:")
for typ, pnl in sorted(pnl_by_type.items(), key=lambda x: -abs(x[1])):
    print(f"  {typ}: ${pnl:.2f}")
print(f"\nMarkets with both SELL+REDEEM PnL: {len(double_markets)}")
print(f"Total PnL in those markets: ${double_count_total:.2f}")
print(f"Oversold positions: {oversold_count}")
