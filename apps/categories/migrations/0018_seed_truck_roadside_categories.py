"""Seed Emergency Roadside for Semi Trucks main category and service subcategories."""

from django.db import migrations

TRUCK_MAIN_NAME = 'Emergency Roadside for Semi Trucks'

TRUCK_SUBCATEGORIES = (
    'Tire Service',
    'Jump Start',
    'Fuel Delivery',
    'Lockout',
    'Roadside Repair',
    'Towing',
)


def forwards(apps, schema_editor):
    Category = apps.get_model('categories', 'Category')
    main = Category.objects.filter(
        name=TRUCK_MAIN_NAME,
        parent__isnull=True,
        type_category='by_order',
        is_truck=True,
    ).first()
    if main is None:
        main = Category.objects.create(
            name=TRUCK_MAIN_NAME,
            type_category='by_order',
            parent=None,
            is_truck=True,
        )
    for sub_name in TRUCK_SUBCATEGORIES:
        if Category.objects.filter(parent=main, name=sub_name, is_truck=True).exists():
            continue
        Category.objects.create(
            name=sub_name,
            type_category='by_order',
            parent=main,
            is_truck=True,
        )


def backwards(apps, schema_editor):
    Category = apps.get_model('categories', 'Category')
    mains = Category.objects.filter(
        name=TRUCK_MAIN_NAME,
        parent__isnull=True,
        type_category='by_order',
        is_truck=True,
    )
    for main in mains:
        Category.objects.filter(parent=main, is_truck=True).delete()
        main.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('categories', '0017_category_is_truck'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
