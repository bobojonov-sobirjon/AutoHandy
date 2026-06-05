from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0049_orderservice_unit_price'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='tip_amount',
            field=models.DecimalField(
                decimal_places=2,
                default=0.0,
                help_text='Optional gratuity left by the client after order completion.',
                max_digits=12,
                verbose_name='Tip amount',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='tip_declined',
            field=models.BooleanField(
                default=False,
                help_text='Client chose "No Thanks" on the post-completion tip prompt.',
                verbose_name='Tip declined',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='tip_paid_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When the tip charge succeeded.',
                null=True,
                verbose_name='Tip paid at',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='tip_stripe_payment_intent_id',
            field=models.CharField(
                blank=True,
                default='',
                max_length=255,
                verbose_name='Tip Stripe PaymentIntent id',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='tip_stripe_payment_status',
            field=models.CharField(
                choices=[
                    ('not_applicable', 'Not applicable'),
                    ('pending', 'Pending'),
                    ('succeeded', 'Succeeded'),
                    ('failed', 'Failed'),
                ],
                default='not_applicable',
                max_length=32,
                verbose_name='Tip Stripe payment status',
            ),
        ),
    ]
