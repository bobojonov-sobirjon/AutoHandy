from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0058_order_truck_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='tip_stripe_payment_amount_cents',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Customer charge for tip including marketplace surcharges.',
                null=True,
                verbose_name='Tip Stripe charged amount (minor units)',
            ),
        ),
    ]
