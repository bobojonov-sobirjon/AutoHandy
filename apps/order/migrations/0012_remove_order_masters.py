# Generated manually

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0011_customer_order_flow'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='order',
            name='masters',
        ),
    ]
