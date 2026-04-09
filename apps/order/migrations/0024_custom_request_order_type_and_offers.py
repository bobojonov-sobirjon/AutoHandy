from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0029_move_rest_from_schedule_to_busy_slot'),
        ('order', '0023_remove_order_preferred_time'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='order_type',
            field=models.CharField(
                choices=[
                    ('standard', 'Standard'),
                    ('sos', 'SOS / Emergency'),
                    ('custom_request', 'Custom request'),
                ],
                default='standard',
                help_text='Standard — order with a chosen master; SOS — emergency assistance',
                max_length=20,
                verbose_name='Order type',
            ),
        ),
        migrations.CreateModel(
            name='CustomRequestOffer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('price', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='Offer price')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated at')),
                (
                    'master',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='custom_request_offers',
                        to='master.master',
                        verbose_name='Master',
                    ),
                ),
                (
                    'order',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='custom_request_offers',
                        to='order.order',
                        verbose_name='Order',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Custom request offer',
                'verbose_name_plural': 'Custom request offers',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='customrequestoffer',
            constraint=models.UniqueConstraint(fields=('order', 'master'), name='uniq_custom_request_offer_order_master'),
        ),
    ]
