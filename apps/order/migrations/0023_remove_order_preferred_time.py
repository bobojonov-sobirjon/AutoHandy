# Generated manually — free-text preferred_time replaced by structured date/time fields.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0022_order_preferred_datetime_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='order',
            name='preferred_time',
        ),
    ]
