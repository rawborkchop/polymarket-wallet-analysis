# Generated migration for updating trade unique constraint

from django.db import migrations, models


def remove_duplicate_trades(apps, schema_editor):
    """Remove duplicate trades that would violate the new unique constraint."""
    Trade = apps.get_model('wallet_analysis', 'Trade')

    # Find duplicates based on the new constraint fields
    from django.db.models import Count, Min
    duplicates = (
        Trade.objects.values('wallet', 'transaction_hash', 'asset', 'market', 'side')
        .annotate(count=Count('id'), min_id=Min('id'))
        .filter(count__gt=1)
    )

    deleted_total = 0
    for dup in duplicates:
        # Keep the oldest record (min id), delete the rest
        to_delete = Trade.objects.filter(
            wallet=dup['wallet'],
            transaction_hash=dup['transaction_hash'],
            asset=dup['asset'],
            market=dup['market'],
            side=dup['side'],
        ).exclude(id=dup['min_id'])
        count = to_delete.count()
        to_delete.delete()
        deleted_total += count

    if deleted_total:
        print(f"\n      Removed {deleted_total} duplicate trades before applying constraint")


class Migration(migrations.Migration):

    dependencies = [
        ('wallet_analysis', '0003_add_activity_unique_constraint'),
    ]

    operations = [
        # Remove old constraint
        migrations.RemoveConstraint(
            model_name='trade',
            name='unique_trade',
        ),
        # Clean duplicates that would violate the new constraint
        migrations.RunPython(remove_duplicate_trades, migrations.RunPython.noop),
        # Add new constraint with wallet and market
        migrations.AddConstraint(
            model_name='trade',
            constraint=models.UniqueConstraint(
                fields=['wallet', 'transaction_hash', 'asset', 'market', 'side'],
                name='unique_trade_v2'
            ),
        ),
    ]
