# Generated manually for order penalty billing

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0046_card_only_payment_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='order_penalty_total',
            field=models.DecimalField(
                decimal_places=2,
                default=0.0,
                help_text='Fixed penalties on this order (e.g. client cancel fee). Added to client payable total; not part of master job payout percentage base.',
                max_digits=12,
                verbose_name='Order penalties total',
            ),
        ),
    ]
