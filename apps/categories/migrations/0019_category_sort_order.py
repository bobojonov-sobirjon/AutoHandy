from django.db import migrations, models


def apply_sort_order(apps, schema_editor):
    from apps.categories.services.home_screen_order import apply_home_screen_category_order

    apply_home_screen_category_order()


class Migration(migrations.Migration):

    dependencies = [
        ('categories', '0018_seed_truck_roadside_categories'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='sort_order',
            field=models.PositiveIntegerField(
                blank=True,
                db_index=True,
                help_text='Lower numbers appear first on the home screen. Leave empty to sort after numbered items.',
                null=True,
                verbose_name='Display order',
            ),
        ),
        migrations.RunPython(apply_sort_order, migrations.RunPython.noop),
    ]
