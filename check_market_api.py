"""Check what Polymarket API tells us about market grouping."""
import os, sys, django, requests, json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'polymarket_project.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from wallet_analysis.models import Market

# Check parent market (conversion target)
parent = Market.objects.filter(title__icontains='Highest temperature in London on November 12?').first()
print(f"Parent: id={parent.id}, condition_id={parent.condition_id}, slug={parent.slug}")

# Check a child market
child = Market.objects.get(id=11802)  # 63-64F
print(f"Child:  id={child.id}, condition_id={child.condition_id}, slug={child.slug}")

# Query Polymarket API for market details
# Try gamma API
for label, cid in [("Parent", parent.condition_id), ("Child", child.condition_id)]:
    print(f"\n=== {label}: {cid} ===")
    # Try gamma markets API
    try:
        r = requests.get(f'https://gamma-api.polymarket.com/markets?condition_ids={cid}', timeout=10)
        if r.status_code == 200 and r.json():
            data = r.json()[0] if isinstance(r.json(), list) else r.json()
            # Look for group/parent fields
            for key in ['group_slug', 'group_item_title', 'neg_risk', 'neg_risk_market_id', 
                        'parent_id', 'condition_id', 'question_id', 'event_slug',
                        'slug', 'question', 'market_slug']:
                if key in data:
                    print(f"  {key}: {data[key]}")
    except Exception as e:
        print(f"  gamma error: {e}")

    # Try CLOB API
    try:
        r2 = requests.get(f'https://clob.polymarket.com/markets/{cid}', timeout=10)
        if r2.status_code == 200:
            data2 = r2.json()
            for key in ['condition_id', 'question_id', 'neg_risk', 'neg_risk_market_id',
                        'neg_risk_request_id', 'question', 'market_slug', 'group_item_title']:
                if key in data2:
                    print(f"  CLOB {key}: {data2[key]}")
    except Exception as e:
        print(f"  CLOB error: {e}")
