from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0051_order_time_change_request'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='order_type',
            field=models.CharField(
                choices=[
                    ('standard', 'Standard'),
                    ('sos', 'SOS / Emergency'),
                    ('custom_request', 'Custom request'),
                    ('towing', 'Towing'),
                ],
                default='standard',
                help_text='Standard — order with a chosen master; SOS — emergency assistance',
                max_length=20,
                verbose_name='Order type',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_latitude',
            field=models.DecimalField(
                blank=True,
                decimal_places=18,
                help_text='Towing: destination GPS latitude.',
                max_digits=22,
                null=True,
                verbose_name='Delivery latitude',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_location',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Towing: destination address where the vehicle should be delivered.',
                verbose_name='Delivery location',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='delivery_longitude',
            field=models.DecimalField(
                blank=True,
                decimal_places=18,
                help_text='Towing: destination GPS longitude.',
                max_digits=22,
                null=True,
                verbose_name='Delivery longitude',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='towing_base_fee',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                verbose_name='Towing base fee (snapshot)',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='towing_distance_miles',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Distance used for towing price (pickup → delivery or client-provided miles).',
                max_digits=8,
                null=True,
                verbose_name='Towing distance (miles)',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='towing_minimum_fee',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                verbose_name='Towing minimum fee (snapshot)',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='towing_price_per_mile',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                verbose_name='Towing price per mile (snapshot)',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='towing_total',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Locked towing job price at order creation.',
                max_digits=12,
                null=True,
                verbose_name='Towing total (snapshot)',
            ),
        ),
    ]
