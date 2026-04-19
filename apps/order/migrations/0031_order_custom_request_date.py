# Generated manually for custom request calendar date

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0030_backfill_completion_pin_in_progress'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='custom_request_date',
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name='Custom request date',
                help_text='Calendar day for the requested service (client local / request date).',
            ),
        ),
    ]
