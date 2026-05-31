# Lock order line prices so master profile edits do not change completed orders.

from decimal import Decimal

from django.db import migrations, models


def backfill_order_service_unit_prices(apps, schema_editor):
    OrderService = apps.get_model('order', 'OrderService')
    for os_row in OrderService.objects.select_related('master_service_item').iterator():
        if os_row.unit_price is not None:
            continue
        item = os_row.master_service_item
        if not item or item.price is None:
            continue
        os_row.unit_price = Decimal(str(item.price)).quantize(Decimal('0.01'))
        os_row.save(update_fields=['unit_price'])


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0048_master_assignment_failure'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderservice',
            name='unit_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text=(
                    'Per-car base price frozen when the line is added (or on order completion). '
                    'Master profile price changes must not alter past orders.'
                ),
                max_digits=12,
                null=True,
                verbose_name='Locked unit price',
            ),
        ),
        migrations.RunPython(backfill_order_service_unit_prices, migrations.RunPython.noop),
    ]
