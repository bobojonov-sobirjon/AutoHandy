from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def split_towing_pricing_by_service_type(apps, schema_editor):
    MasterTowingPricing = apps.get_model('master', 'MasterTowingPricing')
    extra_types = ('long_distance', 'accident_recovery', 'motorcycle')

    for row in MasterTowingPricing.objects.all().iterator():
        local_base = row.local_base_fee if row.local_base_fee > 0 else row.base_fee
        local_rate = row.local_price_per_mile if row.local_price_per_mile > 0 else row.price_per_mile
        long_base = row.long_distance_base_fee
        long_rate = row.long_distance_price_per_mile
        minimum = row.minimum_fee
        active = row.is_active
        master_id = row.master_id

        row.service_type = 'local'
        row.base_fee = local_base
        row.price_per_mile = local_rate
        row.minimum_fee = minimum
        row.save(
            update_fields=['service_type', 'base_fee', 'price_per_mile', 'minimum_fee']
        )

        defaults_by_type = {
            'long_distance': {
                'base_fee': long_base,
                'price_per_mile': long_rate,
                'minimum_fee': minimum,
                'is_active': active and (long_base > 0 or long_rate > 0),
            },
            'accident_recovery': {
                'base_fee': 0,
                'price_per_mile': 0,
                'minimum_fee': 0,
                'is_active': False,
            },
            'motorcycle': {
                'base_fee': 0,
                'price_per_mile': 0,
                'minimum_fee': 0,
                'is_active': False,
            },
        }
        for service_type in extra_types:
            MasterTowingPricing.objects.get_or_create(
                master_id=master_id,
                service_type=service_type,
                defaults=defaults_by_type[service_type],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0035_master_towing_local_long_distance'),
    ]

    operations = [
        migrations.AddField(
            model_name='mastertowingpricing',
            name='service_type',
            field=models.CharField(
                choices=[
                    ('local', 'Local towing'),
                    ('long_distance', 'Long distance towing'),
                    ('accident_recovery', 'Accident recovery'),
                    ('motorcycle', 'Motorcycle towing'),
                ],
                default='local',
                max_length=32,
                verbose_name='Service type',
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='mastertowingpricing',
            name='master',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='towing_pricing_items',
                to='master.master',
                verbose_name='Master',
            ),
        ),
        migrations.RunPython(split_towing_pricing_by_service_type, migrations.RunPython.noop),
        migrations.RemoveField(model_name='mastertowingpricing', name='local_base_fee'),
        migrations.RemoveField(model_name='mastertowingpricing', name='local_price_per_mile'),
        migrations.RemoveField(model_name='mastertowingpricing', name='long_distance_base_fee'),
        migrations.RemoveField(model_name='mastertowingpricing', name='long_distance_price_per_mile'),
        migrations.RemoveField(model_name='mastertowingpricing', name='local_max_miles'),
        migrations.AlterField(
            model_name='mastertowingpricing',
            name='base_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Flat fee for this towing service type (e.g. $80).',
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name='Base fee',
            ),
        ),
        migrations.AlterField(
            model_name='mastertowingpricing',
            name='minimum_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Final price for this service type will not be lower than this amount.',
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name='Minimum total',
            ),
        ),
        migrations.AlterField(
            model_name='mastertowingpricing',
            name='price_per_mile',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Additional charge per mile (e.g. $5).',
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name='Price per mile',
            ),
        ),
        migrations.AlterField(
            model_name='mastertowingpricing',
            name='is_active',
            field=models.BooleanField(
                default=True,
                help_text='When false, master is hidden from estimates for this service type.',
                verbose_name='Active',
            ),
        ),
        migrations.AddConstraint(
            model_name='mastertowingpricing',
            constraint=models.UniqueConstraint(
                fields=('master', 'service_type'),
                name='master_towing_pricing_master_service_type_uniq',
            ),
        ),
        migrations.AlterModelOptions(
            name='mastertowingpricing',
            options={
                'ordering': ['master_id', 'service_type'],
                'verbose_name': 'Master towing pricing',
                'verbose_name_plural': 'Master towing pricing',
            },
        ),
    ]
