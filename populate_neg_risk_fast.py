"""Fast neg-risk population: batch fetch from CLOB API."""
import os, sys, django, requests, time
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Wallet, Trade, Activity, Market

w = Wallet.objects.get(id=8)

# Get all market ids for this wallet
trade_mids = set(Trade.objects.filter(wallet=w).values_list('market_id', flat=True).distinct())
act_mids = set(Activity.objects.filter(wallet=w).values_list('market_id', flat=True).distinct())
all_mids = trade_mids | act_mids

markets = Market.objects.filter(id__in=all_mids, neg_risk_market_id='')
total = markets.count()
print(f"Markets to process: {total}")

session = requests.Session()
session.headers['User-Agent'] = 'PolymarketWalletAnalyzer/1.0'
updated = 0
errors = 0
skipped = 0

for i, market in enumerate(markets):
    if i % 100 == 0:
        print(f"  {i}/{total} processed, {updated} updated, {errors} errors, {skipped} skipped")
    
    try:
        r = session.get(
            f'https://clob.polymarket.com/markets/{market.condition_id}',
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            nr = data.get('neg_risk', False)
            nrmid = data.get('neg_risk_market_id', '') or ''
            if nr or nrmid:
                market.neg_risk = nr
                market.neg_risk_market_id = nrmid
                market.save(update_fields=['neg_risk', 'neg_risk_market_id'])
                updated += 1
            else:
                skipped += 1
        elif r.status_code == 404:
            skipped += 1
        else:
            errors += 1
            print(f"  HTTP {r.status_code} for {market.condition_id[:20]}...")
    except Exception as e:
        errors += 1
        if errors < 5:
            print(f"  Error: {e}")
    
    time.sleep(0.15)  # ~6.5 req/s

print(f"\nDone: {updated} updated, {errors} errors, {skipped} skipped out of {total}")
