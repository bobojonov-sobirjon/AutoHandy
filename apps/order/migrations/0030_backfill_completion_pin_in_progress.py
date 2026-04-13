# Generated manually — PIN for orders already in_progress at deploy time.

import secrets

from django.db import migrations
from django.utils import timezone


def issue_pins_for_in_progress(apps, schema_editor):
    Order = apps.get_model('order', 'Order')
    now = timezone.now()
    for order in Order.objects.filter(status='in_progress').iterator():
        pin = (getattr(order, 'completion_pin', None) or '').strip()
        if len(pin) == 4 and pin.isdigit():
            continue
        order.completion_pin = f'{secrets.randbelow(10000):04d}'
        order.completion_pin_issued_at = now
        order.save(update_fields=['completion_pin', 'completion_pin_issued_at'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0029_order_completion_pin'),
    ]

    operations = [
        migrations.RunPython(issue_pins_for_in_progress, noop_reverse),
    ]
