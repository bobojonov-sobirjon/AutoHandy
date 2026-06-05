import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0032_stripe_identity'),
        ('order', '0050_order_tip_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrderTimeChangeRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('previous_preferred_date', models.DateField(blank=True, null=True, verbose_name='Previous date')),
                ('previous_preferred_time_start', models.TimeField(blank=True, null=True, verbose_name='Previous start')),
                ('previous_preferred_time_end', models.TimeField(blank=True, null=True, verbose_name='Previous end')),
                ('proposed_preferred_date', models.DateField(verbose_name='Proposed date')),
                ('proposed_preferred_time_start', models.TimeField(verbose_name='Proposed start')),
                (
                    'proposed_preferred_time_end',
                    models.TimeField(
                        blank=True,
                        help_text='Required for standard orders; optional for custom request.',
                        null=True,
                        verbose_name='Proposed end',
                    ),
                ),
                ('master_comment', models.TextField(blank=True, default='', verbose_name='Master comment')),
                (
                    'status',
                    models.CharField(
                        choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')],
                        db_index=True,
                        default='pending',
                        max_length=16,
                        verbose_name='Status',
                    ),
                ),
                ('client_comment', models.TextField(blank=True, default='', verbose_name='Client comment')),
                ('decided_at', models.DateTimeField(blank=True, null=True, verbose_name='Decided at')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                (
                    'master',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='time_change_requests',
                        to='master.master',
                        verbose_name='Master',
                    ),
                ),
                (
                    'order',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='time_change_requests',
                        to='order.order',
                        verbose_name='Order',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Order time change request',
                'verbose_name_plural': 'Order time change requests',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['order', 'status'], name='order_time__order_i_6f0f0d_idx'),
                    models.Index(fields=['master', 'status'], name='order_time__master__a2f0c1_idx'),
                ],
            },
        ),
    ]
