# Standard vs SOS: DB value scheduled -> standard; proxy ScheduledOrder -> StandardOrder.

from django.db import migrations, models


def forwards_order_type(apps, schema_editor):
    Order = apps.get_model('order', 'Order')
    Order.objects.filter(order_type='scheduled').update(order_type='standard')


def backwards_order_type(apps, schema_editor):
    Order = apps.get_model('order', 'Order')
    Order.objects.filter(order_type='standard').update(order_type='scheduled')


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0018_remove_order_schedule_datetime_fields'),
    ]

    operations = [
        migrations.RunPython(forwards_order_type, backwards_order_type),
        migrations.AlterField(
            model_name='order',
            name='order_type',
            field=models.CharField(
                choices=[('standard', 'Standard'), ('sos', 'SOS / Emergency')],
                default='standard',
                help_text='Standard — order with a chosen master; SOS — emergency assistance',
                max_length=20,
                verbose_name='Order type',
            ),
        ),
        migrations.RenameModel(
            old_name='ScheduledOrder',
            new_name='StandardOrder',
        ),
        migrations.AlterModelOptions(
            name='standardorder',
            options={
                'ordering': ['-created_at'],
                'verbose_name': 'Standard order',
                'verbose_name_plural': 'Standard orders',
            },
        ),
    ]
