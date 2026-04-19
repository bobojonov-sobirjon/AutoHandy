# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0031_order_custom_request_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='custom_request_time',
            field=models.TimeField(
                blank=True,
                null=True,
                verbose_name='Custom request time',
                help_text='Preferred time of day for the service (client local / same TZ as custom_request_date).',
            ),
        ),
    ]
