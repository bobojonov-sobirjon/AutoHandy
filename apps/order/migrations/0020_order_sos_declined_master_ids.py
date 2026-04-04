# Generated manually for SOS broadcast decline tracking

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0019_order_type_standard_rename_proxy'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='sos_declined_master_ids',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='SOS broadcast: master IDs who declined this offer (still pending).',
                verbose_name='SOS declined master IDs',
            ),
        ),
        migrations.AlterField(
            model_name='order',
            name='sos_offer_queue',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='SOS: nearest master IDs (broadcast to all in zone); first accept wins.',
                verbose_name='SOS offer queue (master IDs)',
            ),
        ),
    ]
