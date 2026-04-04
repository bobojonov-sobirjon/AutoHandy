# Generated manually: drop by_master type — data becomes by_order; choices updated.

from django.db import migrations, models


def forwards_convert_by_master(apps, schema_editor):
    Category = apps.get_model('categories', 'Category')
    Category.objects.filter(type_category='by_master').update(type_category='by_order')


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('categories', '0010_maincategory_subcategory_proxies'),
    ]

    operations = [
        migrations.RunPython(forwards_convert_by_master, noop_reverse),
        migrations.AlterField(
            model_name='category',
            name='type_category',
            field=models.CharField(
                choices=[
                    ('by_car', 'By car category'),
                    ('by_order', 'By order category'),
                ],
                max_length=255,
                verbose_name='Category type',
            ),
        ),
    ]
