from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0037_towing_service_types_cleanup'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='mastertowingpricing',
            name='minimum_fee',
        ),
    ]
