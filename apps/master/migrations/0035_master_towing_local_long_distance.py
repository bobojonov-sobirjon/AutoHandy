from django.core.validators import MinValueValidator
from django.db import migrations, models


def copy_legacy_towing_rates(apps, schema_editor):
    MasterTowingPricing = apps.get_model('master', 'MasterTowingPricing')
    for row in MasterTowingPricing.objects.all():
        if row.local_base_fee <= 0 and row.base_fee > 0:
            row.local_base_fee = row.base_fee
        if row.local_price_per_mile <= 0 and row.price_per_mile > 0:
            row.local_price_per_mile = row.price_per_mile
        row.save(update_fields=['local_base_fee', 'local_price_per_mile', 'base_fee', 'price_per_mile'])


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0034_masterserviceitems_fuel_delivery_containers'),
    ]

    operations = [
        migrations.AddField(
            model_name='mastertowingpricing',
            name='local_base_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Flat fee for local towing (e.g. $80).',
                max_digits=10,
                validators=[MinValueValidator(0)],
                verbose_name='Local base fee',
            ),
        ),
        migrations.AddField(
            model_name='mastertowingpricing',
            name='local_price_per_mile',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Per-mile rate for local towing (e.g. $5).',
                max_digits=10,
                validators=[MinValueValidator(0)],
                verbose_name='Local price per mile',
            ),
        ),
        migrations.AddField(
            model_name='mastertowingpricing',
            name='long_distance_base_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Flat fee for long-distance towing (e.g. $120).',
                max_digits=10,
                validators=[MinValueValidator(0)],
                verbose_name='Long distance base fee',
            ),
        ),
        migrations.AddField(
            model_name='mastertowingpricing',
            name='long_distance_price_per_mile',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Per-mile rate for long-distance towing (e.g. $4).',
                max_digits=10,
                validators=[MinValueValidator(0)],
                verbose_name='Long distance price per mile',
            ),
        ),
        migrations.AddField(
            model_name='mastertowingpricing',
            name='local_max_miles',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Trips up to this distance use local tariff; above uses long-distance. '
                'Falls back to TOWING_LOCAL_MAX_MILES when empty.',
                max_digits=8,
                null=True,
                validators=[MinValueValidator(0)],
                verbose_name='Local max miles',
            ),
        ),
        migrations.RunPython(copy_legacy_towing_rates, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='mastertowingpricing',
            name='base_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Deprecated alias for local_base_fee; kept for backward compatibility.',
                max_digits=10,
                validators=[MinValueValidator(0)],
                verbose_name='Base fee (legacy)',
            ),
        ),
        migrations.AlterField(
            model_name='mastertowingpricing',
            name='price_per_mile',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Deprecated alias for local_price_per_mile.',
                max_digits=10,
                validators=[MinValueValidator(0)],
                verbose_name='Price per mile (legacy)',
            ),
        ),
    ]
