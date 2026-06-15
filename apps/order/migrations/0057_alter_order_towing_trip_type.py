from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0056_order_towing_trip_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='towing_trip_type',
            field=models.CharField(
                blank=True,
                help_text='local, long_distance, accident_recovery, or motorcycle — selected by driver at order creation.',
                max_length=32,
                null=True,
                verbose_name='Towing service type (snapshot)',
            ),
        ),
    ]
