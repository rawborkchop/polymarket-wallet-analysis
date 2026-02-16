"""Analyze Polymarket leaderboard API to understand PnL calculation."""
import os, sys, json, urllib.request
from datetime import datetime, timedelta
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
import django
django.setup()

from wallet_analysis.models import Trade, Activity, Wallet

WALLETS = {
    '1pixel': '0xbdcd1a99e6880b8146f61323dcb799bb5b243e9c',
    'sovereign2013': '0xee613b3fc183ee44f9da9c05f53e2da107e3debf',
}

PERIODS = ['all', 'month', 'week', 'day']
EXTRA_PERIODS = ['year', '3month', '6month', '90d', '30d', '7d', '1d']
CATEGORIES = ['overall', 'weather', 'sports', 'politics', 'crypto', 'pop-culture', 'science']

def fetch_leaderboard(address, period='all', category='overall'):
    url = f'https://data-api.polymarket.com/v1/leaderboard?timePeriod={period}&orderBy=PNL&limit=1&offset=0&category={category}&user={address}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data
    except Exception as e:
        return {'error': str(e)}

def fetch_top_leaderboard(period='all', limit=5):
    url = f'https://data-api.polymarket.com/v1/leaderboard?timePeriod={period}&orderBy=PNL&limit={limit}&offset=0&category=overall'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {'error': str(e)}

def calc_cashflow(wallet_id, since_dt=None):
    """Cash flow PnL: sells + redeems + merges + rewards - buys - splits"""
    trades = Trade.objects.filter(wallet_id=wallet_id)
    activities = Activity.objects.filter(wallet_id=wallet_id)
    if since_dt:
        trades = trades.filter(datetime__gte=since_dt)
        activities = activities.filter(datetime__gte=since_dt)
    
    buys = trades.filter(side='BUY').values_list('total_value', flat=True)
    sells = trades.filter(side='SELL').values_list('total_value', flat=True)
    buy_cost = sum(buys, Decimal(0))
    sell_rev = sum(sells, Decimal(0))
    
    redeems = sum(activities.filter(activity_type='REDEEM').values_list('usdc_size', flat=True), Decimal(0))
    splits = sum(activities.filter(activity_type='SPLIT').values_list('usdc_size', flat=True), Decimal(0))
    merges = sum(activities.filter(activity_type='MERGE').values_list('usdc_size', flat=True), Decimal(0))
    rewards = sum(activities.filter(activity_type='REWARD').values_list('usdc_size', flat=True), Decimal(0))
    conversions = sum(activities.filter(activity_type='CONVERSION').values_list('usdc_size', flat=True), Decimal(0))
    
    pnl = sell_rev + redeems + merges + rewards + conversions - buy_cost - splits
    return {
        'buy_cost': float(buy_cost), 'sell_rev': float(sell_rev),
        'redeems': float(redeems), 'splits': float(splits),
        'merges': float(merges), 'rewards': float(rewards),
        'conversions': float(conversions), 'pnl': float(pnl)
    }

print("=" * 80)
print("POLYMARKET LEADERBOARD API ANALYSIS")
print("=" * 80)

# 1. Fetch leaderboard for known wallets across periods
all_results = {}
for name, addr in WALLETS.items():
    all_results[name] = {}
    print(f"\n### {name} ({addr[:10]}...)")
    for period in PERIODS:
        data = fetch_leaderboard(addr, period)
        all_results[name][period] = data
        if isinstance(data, list) and len(data) > 0:
            d = data[0]
            print(f"  {period:>6}: PnL=${d.get('pnl', 'N/A'):>12}  volume=${d.get('volume', 'N/A'):>12}  markets={d.get('marketsTraded', 'N/A')}")
            # Print all keys for first result
            if period == 'all':
                print(f"    All keys: {list(d.keys())}")
        else:
            print(f"  {period:>6}: {data}")

# 2. Top leaderboard wallets
print("\n\n### TOP 5 ALL-TIME")
top = fetch_top_leaderboard('all', 5)
if isinstance(top, list):
    for i, t in enumerate(top):
        print(f"  #{i+1}: {t.get('pseudonym', t.get('proxyWallet','?')[:10])} PnL=${t.get('pnl', 'N/A')}")
        # Fetch their month too
        addr = t.get('proxyWallet') or t.get('userAddress', '')
        if addr:
            month_data = fetch_leaderboard(addr, 'month')
            if isinstance(month_data, list) and month_data:
                print(f"       month PnL=${month_data[0].get('pnl', 'N/A')}")

# 3. Try extra periods
print("\n\n### EXTRA PERIODS for 1pixel")
for p in EXTRA_PERIODS:
    data = fetch_leaderboard(WALLETS['1pixel'], p)
    if isinstance(data, list) and len(data) > 0:
        print(f"  {p:>8}: PnL=${data[0].get('pnl', 'N/A')}")
    else:
        print(f"  {p:>8}: {data}")

# 4. Try categories for 1pixel
print("\n\n### CATEGORIES for 1pixel (all-time)")
for cat in CATEGORIES:
    data = fetch_leaderboard(WALLETS['1pixel'], 'all', cat)
    if isinstance(data, list) and len(data) > 0:
        print(f"  {cat:>15}: PnL=${data[0].get('pnl', 'N/A')}")
    else:
        print(f"  {cat:>15}: empty/error")

# 5. Our cash flow calculations
print("\n\n### OUR CASH FLOW for 1pixel")
now = datetime.utcnow()
wallet_id = 7
periods_dt = {
    'all': None,
    'month': now - timedelta(days=30),
    'week': now - timedelta(days=7),
    'day': now - timedelta(days=1),
}
our_results = {}
for period_name, since in periods_dt.items():
    cf = calc_cashflow(wallet_id, since)
    our_results[period_name] = cf
    print(f"  {period_name:>6}: PnL=${cf['pnl']:>12.2f}  (buys=${cf['buy_cost']:.2f} sells=${cf['sell_rev']:.2f} redeems=${cf['redeems']:.2f} splits=${cf['splits']:.2f} merges=${cf['merges']:.2f} rewards=${cf['rewards']:.2f})")

# 6. Compare ratios
print("\n\n### RATIOS: PM PnL / Our Cash Flow PnL")
pm_1pixel = all_results.get('1pixel', {})
for period in PERIODS:
    pm_data = pm_1pixel.get(period, [])
    pm_pnl = None
    if isinstance(pm_data, list) and pm_data:
        pm_pnl = pm_data[0].get('pnl')
    our_pnl = our_results.get(period, {}).get('pnl')
    if pm_pnl is not None and our_pnl and our_pnl != 0:
        ratio = float(pm_pnl) / our_pnl
        print(f"  {period:>6}: PM=${pm_pnl:>12}  Ours=${our_pnl:>12.2f}  Ratio={ratio:.4f}")
    else:
        print(f"  {period:>6}: PM={pm_pnl}  Ours={our_pnl}  (can't compute ratio)")

# 7. Consistency checks
print("\n\n### CONSISTENCY CHECKS")
if isinstance(pm_1pixel.get('all'), list) and pm_1pixel['all']:
    pm_all = float(pm_1pixel['all'][0].get('pnl', 0))
    pm_month = float(pm_1pixel['month'][0].get('pnl', 0)) if isinstance(pm_1pixel.get('month'), list) and pm_1pixel['month'] else 0
    pm_week = float(pm_1pixel['week'][0].get('pnl', 0)) if isinstance(pm_1pixel.get('week'), list) and pm_1pixel['week'] else 0
    pm_day = float(pm_1pixel['day'][0].get('pnl', 0)) if isinstance(pm_1pixel.get('day'), list) and pm_1pixel['day'] else 0
    print(f"  PM all={pm_all}  month={pm_month}  week={pm_week}  day={pm_day}")
    print(f"  all - month = {pm_all - pm_month:.2f} (PnL before this month)")
    print(f"  month - week = {pm_month - pm_week:.2f} (month excluding last week)")
    print(f"  week - day = {pm_week - pm_day:.2f} (week excluding today)")

# 8. Look at PM response fields in detail
print("\n\n### FULL PM RESPONSE for 1pixel ALL")
if isinstance(pm_1pixel.get('all'), list) and pm_1pixel['all']:
    for k, v in sorted(pm_1pixel['all'][0].items()):
        print(f"  {k}: {v}")

print("\n\n### FULL PM RESPONSE for 1pixel MONTH")
if isinstance(pm_1pixel.get('month'), list) and pm_1pixel['month']:
    for k, v in sorted(pm_1pixel['month'][0].items()):
        print(f"  {k}: {v}")

print("\nDone!")
