from django.db import migrations


def backfill_busy_slots(apps, schema_editor):
    Order = apps.get_model('order', 'Order')
    MasterBusySlot = apps.get_model('master', 'MasterBusySlot')
    for o in Order.objects.filter(master_id__isnull=False).iterator():
        if getattr(o, 'order_type', None) != 'scheduled':
            continue
        if not o.scheduled_date or not o.scheduled_time_start or not o.scheduled_time_end:
            continue
        if o.status in ('cancelled', 'rejected'):
            continue
        MasterBusySlot.objects.update_or_create(
            order_id=o.id,
            defaults={
                'master_id': o.master_id,
                'date': o.scheduled_date,
                'start_time': o.scheduled_time_start,
                'end_time': o.scheduled_time_end,
                'reason': '',
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0022_skills_schedule_refactor'),
        ('order', '0010_alter_order_options_alter_orderservice_options_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_busy_slots, migrations.RunPython.noop),
    ]
