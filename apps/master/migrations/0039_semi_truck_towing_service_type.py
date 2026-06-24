from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0038_remove_towing_minimum_fee'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mastertowingpricing',
            name='service_type',
            field=models.CharField(
                choices=[
                    ('local', 'Local towing'),
                    ('long_distance', 'Long distance towing'),
                    ('accident_recovery', 'Accident recovery'),
                    ('motorcycle', 'Motorcycle towing'),
                    ('semi_truck', 'Semi-truck towing'),
                ],
                max_length=32,
                verbose_name='Service type',
            ),
        ),
    ]
