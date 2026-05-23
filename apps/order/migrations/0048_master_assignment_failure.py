from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0001_initial'),
        ('order', '0047_order_order_penalty_total'),
    ]

    operations = [
        migrations.CreateModel(
            name='MasterAssignmentFailure',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                (
                    'reason',
                    models.CharField(
                        choices=[
                            ('sos_no_departure', 'SOS: no departure after accept'),
                            ('standard_no_departure', 'Standard: no departure after accept'),
                            ('scheduled_no_start', 'Scheduled: did not start by deadline'),
                        ],
                        max_length=32,
                        verbose_name='Reason',
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                (
                    'master',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='assignment_failures',
                        to='master.master',
                        verbose_name='Master',
                    ),
                ),
                (
                    'order',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='assignment_failures',
                        to='order.order',
                        verbose_name='Order',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Master assignment failure',
                'verbose_name_plural': 'Master assignment failures',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='masterassignmentfailure',
            constraint=models.UniqueConstraint(
                fields=('master', 'order', 'reason'),
                name='uniq_master_assignment_failure_master_order_reason',
            ),
        ),
    ]
