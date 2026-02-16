from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wallet_analysis', '0007_add_asset_outcome_to_activity'),
    ]

    operations = [
        migrations.AlterField(
            model_name='market',
            name='winning_outcome',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
