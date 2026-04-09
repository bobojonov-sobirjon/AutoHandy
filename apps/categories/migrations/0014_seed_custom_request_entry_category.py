"""Ensure one main by_order category exists for client-only Custom Request orders."""

from django.db import migrations


def forwards(apps, schema_editor):
    Category = apps.get_model('categories', 'Category')
    if Category.objects.filter(
        is_custom_request_entry=True,
        parent__isnull=True,
        type_category='by_order',
    ).exists():
        return
    Category.objects.create(
        name='Custom Request',
        type_category='by_order',
        parent=None,
        is_custom_request_entry=True,
    )


def backwards(apps, schema_editor):
    Category = apps.get_model('categories', 'Category')
    Category.objects.filter(
        name='Custom Request',
        parent__isnull=True,
        type_category='by_order',
        is_custom_request_entry=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('categories', '0013_category_is_custom_request_entry'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
