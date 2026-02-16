from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wallet_analysis', '0008_market_winning_outcome_default'),
    ]

    operations = [
        migrations.AddField(
            model_name='analysisrun',
            name='avg_cost_cache',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='analysisrun',
            name='avg_cost_cache_activity_count',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='analysisrun',
            name='avg_cost_cache_trade_count',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='analysisrun',
            name='avg_cost_cache_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
