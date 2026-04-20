from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('order', '0032_order_custom_request_time'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='arrival_deadline_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Arrival deadline',
                help_text='Auto-cancel cutoff when master did not arrive in time (ETA + grace).',
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='auto_cancel_reason',
            field=models.CharField(
                blank=True,
                default='',
                max_length=32,
                verbose_name='Auto-cancel reason',
                help_text='Internal reason code when the system cancels an order automatically.',
            ),
        ),
    ]

