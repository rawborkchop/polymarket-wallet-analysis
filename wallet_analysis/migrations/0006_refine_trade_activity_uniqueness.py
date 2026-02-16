from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wallet_analysis', '0005_update_activity_unique_constraint'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='trade',
            name='unique_trade_v2',
        ),
        migrations.AddConstraint(
            model_name='trade',
            constraint=models.UniqueConstraint(
                fields=[
                    'wallet', 'transaction_hash', 'asset', 'market', 'side',
                    'timestamp', 'outcome', 'price', 'size', 'total_value'
                ],
                name='unique_trade_v3',
            ),
        ),
        migrations.RemoveConstraint(
            model_name='activity',
            name='unique_activity_v2',
        ),
        migrations.AddConstraint(
            model_name='activity',
            constraint=models.UniqueConstraint(
                fields=[
                    'wallet', 'transaction_hash', 'activity_type', 'market',
                    'timestamp', 'size', 'usdc_size'
                ],
                name='unique_activity_v3',
            ),
        ),
    ]
