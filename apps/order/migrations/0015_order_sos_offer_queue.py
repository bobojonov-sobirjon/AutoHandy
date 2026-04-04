# Generated manually for SOS WebSocket ring routing

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0014_workflow_celery_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='sos_offer_queue',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='SOS: ordered master IDs (nearest first) for sequential offers.',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='sos_offer_index',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text='SOS: current index in sos_offer_queue.',
            ),
        ),
    ]
