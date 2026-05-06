from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0039_order_extra_money_orderservice_count'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrderExtraMoneyRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, help_text='Requested extra money increment (positive).', max_digits=12, verbose_name='Amount')),
                ('master_comment', models.TextField(blank=True, default='', help_text='Reason/description for the extra money request.', verbose_name='Master comment')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], db_index=True, default='pending', max_length=16, verbose_name='Status')),
                ('client_comment', models.TextField(blank=True, default='', help_text='Required when rejecting (reason).', verbose_name='Client comment')),
                ('decided_at', models.DateTimeField(blank=True, null=True, verbose_name='Decided at')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                ('master', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='extra_money_requests', to='master.master', verbose_name='Master')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='extra_money_requests', to='order.order', verbose_name='Order')),
            ],
            options={
                'verbose_name': 'Order extra money request',
                'verbose_name_plural': 'Order extra money requests',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='orderextramoneyrequest',
            index=models.Index(fields=['order', 'status'], name='order_order__status_idx'),
        ),
        migrations.AddIndex(
            model_name='orderextramoneyrequest',
            index=models.Index(fields=['master', 'status'], name='order_master__status_idx'),
        ),
    ]

