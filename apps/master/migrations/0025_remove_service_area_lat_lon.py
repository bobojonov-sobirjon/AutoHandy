from django.db import migrations


def copy_service_area_coords_to_profile(apps, schema_editor):
    Master = apps.get_model('master', 'Master')
    for m in Master.objects.all():
        if m.latitude is None and m.longitude is None:
            if m.service_area_latitude is not None and m.service_area_longitude is not None:
                Master.objects.filter(pk=m.pk).update(
                    latitude=m.service_area_latitude,
                    longitude=m.service_area_longitude,
                )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0024_master_service_area'),
    ]

    operations = [
        migrations.RunPython(copy_service_area_coords_to_profile, noop_reverse),
        migrations.RemoveField(
            model_name='master',
            name='service_area_latitude',
        ),
        migrations.RemoveField(
            model_name='master',
            name='service_area_longitude',
        ),
    ]
