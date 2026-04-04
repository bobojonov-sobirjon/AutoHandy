# Generated manually: drop visit date/time on Order per product spec.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0017_review_tag_negative_choices'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='scheduledorder',
            options={
                'ordering': ['-created_at'],
                'verbose_name': 'Scheduled order',
                'verbose_name_plural': 'Scheduled orders',
            },
        ),
        migrations.RemoveField(
            model_name='order',
            name='scheduled_date',
        ),
        migrations.RemoveField(
            model_name='order',
            name='scheduled_time_end',
        ),
        migrations.RemoveField(
            model_name='order',
            name='scheduled_time_start',
        ),
    ]
