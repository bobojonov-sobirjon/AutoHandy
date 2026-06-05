import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0032_stripe_identity'),
    ]

    operations = [
        migrations.CreateModel(
            name='MasterTowingPricing',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('base_fee', models.DecimalField(
                    decimal_places=2,
                    default=0,
                    help_text='Flat fee charged for every towing job (e.g. $80).',
                    max_digits=10,
                    validators=[django.core.validators.MinValueValidator(0)],
                    verbose_name='Base fee',
                )),
                ('price_per_mile', models.DecimalField(
                    decimal_places=2,
                    default=0,
                    help_text='Additional charge per mile (e.g. $5).',
                    max_digits=10,
                    validators=[django.core.validators.MinValueValidator(0)],
                    verbose_name='Price per mile',
                )),
                ('minimum_fee', models.DecimalField(
                    decimal_places=2,
                    default=0,
                    help_text='Final price will not be lower than this amount.',
                    max_digits=10,
                    validators=[django.core.validators.MinValueValidator(0)],
                    verbose_name='Minimum total',
                )),
                ('is_active', models.BooleanField(
                    default=True,
                    help_text='When false, master is hidden from towing estimates.',
                    verbose_name='Active',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('master', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='towing_pricing',
                    to='master.master',
                    verbose_name='Master',
                )),
            ],
            options={
                'verbose_name': 'Master towing pricing',
                'verbose_name_plural': 'Master towing pricing',
            },
        ),
    ]
