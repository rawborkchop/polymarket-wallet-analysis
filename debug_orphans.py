import sys,os,django
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DJANGO_SETTINGS_MODULE']='polymarket_project.settings'
django.setup()
from wallet_analysis.models import Activity, Trade, Market

buy_markets = set(Trade.objects.filter(wallet_id=7, side='BUY').values_list('market_id', flat=True))
sell_markets = set(Trade.objects.filter(wallet_id=7, side='SELL').values_list('market_id', flat=True))
split_markets = set(Activity.objects.filter(wallet_id=7, activity_type='SPLIT').values_list('market_id', flat=True))
conv_markets = set(Activity.objects.filter(wallet_id=7, activity_type='CONVERSION').values_list('market_id', flat=True))
orphans = sell_markets - buy_markets - split_markets - conv_markets

# Check a few orphans
for oid in list(orphans)[:3]:
    m = Market.objects.get(id=oid)
    print(f"Orphan market {oid}: {m.title[:80]}")
    for t in Trade.objects.filter(wallet_id=7, market_id=oid).order_by('timestamp')[:3]:
        print(f"  {t.side} {t.outcome} size={t.size} price={t.price} ts={t.datetime}")
    for a in Activity.objects.filter(wallet_id=7, market_id=oid).order_by('timestamp')[:3]:
        print(f"  {a.activity_type} size={a.size} usdc={a.usdc_size}")
    
    # Check if a SPLIT or CONVERSION exists for a RELATED market (same title pattern)
    # Actually check: maybe the tokens come from a SPLIT of a DIFFERENT market
    # that shares the same condition/token
    print()

# Better approach: check if orphan markets are child markets of conversion parents
# Look at market titles
print("Sample orphan titles:")
for oid in list(orphans)[:10]:
    m = Market.objects.get(id=oid)
    print(f"  {m.title[:100]}")

print("\nSample conversion target titles:")
for cid in list(conv_markets)[:10]:
    m = Market.objects.get(id=cid)
    print(f"  {m.title[:100]}")
