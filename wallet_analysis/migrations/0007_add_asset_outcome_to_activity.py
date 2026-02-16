from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wallet_analysis', '0006_refine_trade_activity_uniqueness'),
    ]

    operations = [
        migrations.AddField(
            model_name='activity',
            name='asset',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='activity',
            name='outcome',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
    ]
