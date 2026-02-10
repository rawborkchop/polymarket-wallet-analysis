# Migration to add wallet to activity unique constraint

from django.db import migrations, models


def remove_duplicate_activities(apps, schema_editor):
    """Remove duplicate activities that would violate the new unique constraint."""
    Activity = apps.get_model('wallet_analysis', 'Activity')

    from django.db.models import Count, Min
    duplicates = (
        Activity.objects.values('wallet', 'transaction_hash', 'activity_type', 'size', 'usdc_size')
        .annotate(count=Count('id'), min_id=Min('id'))
        .filter(count__gt=1)
    )

    deleted_total = 0
    for dup in duplicates:
        to_delete = Activity.objects.filter(
            wallet=dup['wallet'],
            transaction_hash=dup['transaction_hash'],
            activity_type=dup['activity_type'],
            size=dup['size'],
            usdc_size=dup['usdc_size'],
        ).exclude(id=dup['min_id'])
        count = to_delete.count()
        to_delete.delete()
        deleted_total += count

    if deleted_total:
        print(f"\n      Removed {deleted_total} duplicate activities before applying constraint")


class Migration(migrations.Migration):

    dependencies = [
        ('wallet_analysis', '0004_update_trade_unique_constraint'),
    ]

    operations = [
        # Remove old constraint without wallet
        migrations.RemoveConstraint(
            model_name='activity',
            name='unique_activity',
        ),
        # Clean duplicates that would violate the new constraint
        migrations.RunPython(remove_duplicate_activities, migrations.RunPython.noop),
        # Add new constraint including wallet
        migrations.AddConstraint(
            model_name='activity',
            constraint=models.UniqueConstraint(
                fields=['wallet', 'transaction_hash', 'activity_type', 'size', 'usdc_size'],
                name='unique_activity_v2'
            ),
        ),
    ]
