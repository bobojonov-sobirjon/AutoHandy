from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0055_order_fuel_delivery_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='towing_trip_type',
            field=models.CharField(
                blank=True,
                help_text='local or long_distance — tariff used when the order was created.',
                max_length=20,
                null=True,
                verbose_name='Towing trip type (snapshot)',
            ),
        ),
    ]
