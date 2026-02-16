import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
django.setup()
from decimal import Decimal
from wallet_analysis.models import Wallet, Trade, Activity, Market
from wallet_analysis.calculators.position_tracker import PositionTracker, ZERO

wallet = Wallet.objects.get(id=7)
trades = list(Trade.objects.filter(wallet=wallet).order_by('timestamp'))
activities = list(Activity.objects.filter(wallet=wallet).order_by('timestamp'))

tracker = PositionTracker()
market_resolutions = {}
for m in Market.objects.filter(resolved=True).exclude(winning_outcome=''):
    market_resolutions[str(m.id)] = m.winning_outcome

db_market_assets = {}
for row in Trade.objects.filter(wallet=wallet).exclude(asset='').exclude(outcome='').values('market_id','outcome','asset').distinct():
    mid = str(row['market_id'])
    if mid not in db_market_assets: db_market_assets[mid] = {}
    db_market_assets[mid][row['outcome']] = row['asset']

positions, realized_events = tracker.process_events(trades, activities, market_resolutions, db_market_assets=db_market_assets)

# Count realized events at redeem timestamps
redeem_ts_to_usdc = {}
for a in activities:
    if a.activity_type == 'REDEEM':
        redeem_ts_to_usdc[a.timestamp] = Decimal(str(a.usdc_size))

redeem_pnl_events = [e for e in realized_events if e.timestamp in redeem_ts_to_usdc]
loser_pnl_events = [e for e in redeem_pnl_events if redeem_ts_to_usdc.get(e.timestamp, Decimal('1')) == 0]
winner_pnl_events = [e for e in redeem_pnl_events if redeem_ts_to_usdc.get(e.timestamp, 0) > 0]

print(f"Redeem activities: winner={len([a for a in activities if a.activity_type=='REDEEM' and Decimal(str(a.usdc_size)) > 0])}, loser={len([a for a in activities if a.activity_type=='REDEEM' and Decimal(str(a.usdc_size)) == 0])}")
print(f"Realized events from redeems: {len(redeem_pnl_events)}")
print(f"  Winner redeem PnL events: {len(winner_pnl_events)}, total: ${sum(e.amount for e in winner_pnl_events):.2f}")
print(f"  Loser redeem PnL events: {len(loser_pnl_events)}, total: ${sum(e.amount for e in loser_pnl_events):.2f}")

# How many loser redeems generated NO PnL event?
loser_timestamps = set(a.timestamp for a in activities if a.activity_type == 'REDEEM' and Decimal(str(a.usdc_size)) == 0)
loser_event_ts = set(e.timestamp for e in loser_pnl_events)
missed_count = len(loser_timestamps - loser_event_ts)
print(f"\nLoser redeem timestamps with no PnL event: {missed_count} out of {len(loser_timestamps)}")

# What's the total cost basis we're missing for those skipped loser redeems?
# For each missed loser redeem, find the position and what cost basis would have been lost
missed_ts = loser_timestamps - loser_event_ts
missed_activities = [a for a in activities if a.activity_type == 'REDEEM' and Decimal(str(a.usdc_size)) == 0 and a.timestamp in missed_ts]

# Check SIMPLE cash flow PnL
buy_cost = sum(Decimal(str(t.total_value)) for t in trades if t.side == 'BUY')
sell_rev = sum(Decimal(str(t.total_value)) for t in trades if t.side == 'SELL')
redeem_rev = sum(Decimal(str(a.usdc_size)) for a in activities if a.activity_type == 'REDEEM')
split_cost = sum(Decimal(str(a.usdc_size)) for a in activities if a.activity_type == 'SPLIT')
merge_rev = sum(Decimal(str(a.usdc_size)) for a in activities if a.activity_type == 'MERGE')
reward_rev = sum(Decimal(str(a.usdc_size)) for a in activities if a.activity_type == 'REWARD')
conv_rev = sum(Decimal(str(a.usdc_size)) for a in activities if a.activity_type == 'CONVERSION')

cash_flow_pnl = sell_rev + redeem_rev + merge_rev + reward_rev + conv_rev - buy_cost - split_cost
print(f"\n=== SIMPLE CASH FLOW PNL ===")
print(f"Buy cost:     ${buy_cost:.2f}")
print(f"Sell revenue: ${sell_rev:.2f}")
print(f"Redeem rev:   ${redeem_rev:.2f}")
print(f"Split cost:   ${split_cost:.2f}")
print(f"Merge rev:    ${merge_rev:.2f}")
print(f"Reward rev:   ${reward_rev:.2f}")
print(f"Conv rev:     ${conv_rev:.2f}")
print(f"Cash flow PnL: ${cash_flow_pnl:.2f}")
print(f"Cost basis PnL: ${sum(e.amount for e in realized_events):.2f}")
print(f"Official PnL: $20,173")

# Check: positions with remaining quantity (open positions that haven't been sold/redeemed)
open_positions = [(a, p) for a, p in positions.items() if p.quantity > 0 and p.total_bought > 0]
total_open_cost = sum(p.avg_price * p.quantity for _, p in open_positions)
print(f"\n=== OPEN POSITIONS ===")
print(f"Open positions: {len(open_positions)}")
print(f"Total open position cost basis: ${total_open_cost:.2f}")
print(f"If all open positions went to 0: PnL would drop by ${total_open_cost:.2f}")
print(f"Adjusted PnL (assuming all open = loss): ${sum(e.amount for e in realized_events) - total_open_cost:.2f}")
