"""Ensure one main by_order category exists for client-only Towing orders."""

from django.db import migrations


def forwards(apps, schema_editor):
    Category = apps.get_model('categories', 'Category')
    if Category.objects.filter(
        is_towing_entry=True,
        parent__isnull=True,
        type_category='by_order',
    ).exists():
        return
    Category.objects.create(
        name='Towing',
        type_category='by_order',
        parent=None,
        is_towing_entry=True,
    )


def backwards(apps, schema_editor):
    Category = apps.get_model('categories', 'Category')
    Category.objects.filter(
        name='Towing',
        parent__isnull=True,
        type_category='by_order',
        is_towing_entry=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('categories', '0015_category_is_towing_entry'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
