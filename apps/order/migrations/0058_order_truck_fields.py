from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0057_alter_order_towing_trip_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='truck_make_model',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Semi-truck orders: client-entered truck name (no passenger car profile).',
                max_length=255,
                verbose_name='Truck make and model',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='truck_year',
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text='Optional model year for semi-truck orders.',
                null=True,
                verbose_name='Truck year',
            ),
        ),
    ]
