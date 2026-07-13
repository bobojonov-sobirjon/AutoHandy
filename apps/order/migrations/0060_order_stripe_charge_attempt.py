from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0059_order_tip_stripe_payment_amount_cents'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='stripe_charge_attempt',
            field=models.PositiveIntegerField(
                default=1,
                help_text=(
                    "Idempotency attempt for job charge on complete. Increments after a failed charge "
                    "so a later retry is not stuck replaying Stripe's cached decline "
                    '(e.g. insufficient funds).'
                ),
                verbose_name='Stripe complete-charge attempt',
            ),
        ),
    ]
