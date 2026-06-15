from django.db import migrations, models
import django.core.validators


LEGACY_COLUMNS = (
    'local_base_fee',
    'local_price_per_mile',
    'long_distance_base_fee',
    'long_distance_price_per_mile',
    'local_max_miles',
)


def drop_legacy_towing_columns(apps, schema_editor):
    """Idempotent: safe if an older combined migration already removed these columns."""
    connection = schema_editor.connection
    table = 'master_mastertowingpricing'
    with connection.cursor() as cursor:
        for column in LEGACY_COLUMNS:
            cursor.execute(
                f'ALTER TABLE {table} DROP COLUMN IF EXISTS {column};'
            )


def add_unique_constraint_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    constraint_name = 'master_towing_pricing_master_service_type_uniq'
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM pg_constraint
            WHERE conname = %s
            """,
            [constraint_name],
        )
        if cursor.fetchone():
            return
        cursor.execute(
            """
            ALTER TABLE master_mastertowingpricing
            ADD CONSTRAINT master_towing_pricing_master_service_type_uniq
            UNIQUE (master_id, service_type);
            """
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('master', '0036_towing_service_types'),
    ]

    operations = [
        migrations.RunPython(drop_legacy_towing_columns, migrations.RunPython.noop),
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
        migrations.RunPython(add_unique_constraint_if_missing, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name='mastertowingpricing',
            options={
                'ordering': ['master_id', 'service_type'],
                'verbose_name': 'Master towing pricing',
                'verbose_name_plural': 'Master towing pricing',
            },
        ),
    ]
