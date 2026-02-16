"""Management command: fetch neg_risk metadata from CLOB API for all markets."""
import time
import requests
from django.core.management.base import BaseCommand
from wallet_analysis.models import Market


class Command(BaseCommand):
    help = 'Populate neg_risk and neg_risk_market_id from Polymarket CLOB API'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Re-fetch even if already populated')
        parser.add_argument('--wallet-id', type=int, help='Only process markets for this wallet')

    def handle(self, *args, **options):
        force = options.get('force', False)

        if options.get('wallet_id'):
            from wallet_analysis.models import Trade, Activity
            trade_mids = set(Trade.objects.filter(wallet_id=options['wallet_id']).values_list('market_id', flat=True))
            act_mids = set(Activity.objects.filter(wallet_id=options['wallet_id']).values_list('market_id', flat=True))
            all_mids = trade_mids | act_mids
            markets = Market.objects.filter(id__in=all_mids)
        else:
            markets = Market.objects.all()

        if not force:
            markets = markets.filter(neg_risk_market_id='')

        total = markets.count()
        self.stdout.write(f'Processing {total} markets...')

        updated = 0
        errors = 0
        session = requests.Session()

        for i, market in enumerate(markets.iterator()):
            if i % 50 == 0 and i > 0:
                self.stdout.write(f'  {i}/{total} processed, {updated} updated, {errors} errors')

            try:
                r = session.get(
                    f'https://clob.polymarket.com/markets/{market.condition_id}',
                    timeout=10
                )
                if r.status_code == 200:
                    data = r.json()
                    nr = data.get('neg_risk', False)
                    nrmid = data.get('neg_risk_market_id', '') or ''
                    if nr != market.neg_risk or nrmid != market.neg_risk_market_id:
                        market.neg_risk = nr
                        market.neg_risk_market_id = nrmid
                        market.save(update_fields=['neg_risk', 'neg_risk_market_id'])
                        updated += 1
                elif r.status_code == 404:
                    pass  # Market not found in CLOB (old/delisted)
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                if errors < 5:
                    self.stderr.write(f'  Error for {market.condition_id}: {e}')

            # Rate limit: ~5 req/s
            time.sleep(0.2)

        self.stdout.write(self.style.SUCCESS(
            f'Done. {updated} updated, {errors} errors out of {total}.'
        ))
