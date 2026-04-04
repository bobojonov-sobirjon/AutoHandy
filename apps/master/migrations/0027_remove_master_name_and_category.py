# Generated manually

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0026_alter_master_latitude_alter_master_longitude_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='master',
            name='category',
        ),
        migrations.RemoveField(
            model_name='master',
            name='name',
        ),
    ]
