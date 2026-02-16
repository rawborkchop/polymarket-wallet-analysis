"""Understand what CONVERSIONs are and if they contribute to PnL"""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'polymarket_project.settings'
django.setup()

from decimal import Decimal
from wallet_analysis.models import Wallet, Activity

w = Wallet.objects.get(id=7)
convs = Activity.objects.filter(wallet=w, activity_type='CONVERSION').order_by('timestamp')

print(f"Total CONVERSIONs: {convs.count()}")
print(f"Total USDC: ${sum(Decimal(str(c.usdc_size)) for c in convs):.2f}")

# Look at a few
print("\n=== SAMPLE CONVERSIONs ===")
for c in convs[:10]:
    print(f"  market={c.market_id} size={c.size} usdc={c.usdc_size} asset={c.asset[:20] if c.asset else 'empty'} outcome={c.outcome} tx={c.transaction_hash[:20] if c.transaction_hash else ''}")

# Are there conversion pairs (same tx, different direction)?
from collections import Counter
tx_counts = Counter(c.transaction_hash for c in convs if c.transaction_hash)
pairs = {tx: cnt for tx, cnt in tx_counts.items() if cnt > 1}
print(f"\nConversions with same tx hash (pairs): {len(pairs)}")
if pairs:
    for tx, cnt in list(pairs.items())[:5]:
        pair_acts = convs.filter(transaction_hash=tx)
        print(f"  tx={tx[:20]}... count={cnt}")
        for a in pair_acts:
            print(f"    market={a.market_id} size={a.size} usdc={a.usdc_size}")

# Gap analysis: maybe conversions are partial inflows
# $889 gap / 254 conversions = $3.50 per conversion average
# Or maybe some specific conversions bridge the gap
print(f"\n=== GAP ANALYSIS ===")
print(f"Gap to close: $889.59")
print(f"Average per conversion: ${Decimal('889.59') / 254:.2f}")

# Check if any conversion has net cash flow implications
# Maybe PM counts some conversions differently
unique_markets = set(c.market_id for c in convs)
print(f"Unique markets with conversions: {len(unique_markets)}")
