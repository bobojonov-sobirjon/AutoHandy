# Generated manually: multiple review tags + review images

import django.db.models.deletion
from django.db import migrations, models


def copy_tag_to_tags(apps, schema_editor):
    Review = apps.get_model('order', 'Review')
    for row in Review.objects.all().iterator():
        tag_val = getattr(row, 'tag', None)
        if tag_val:
            Review.objects.filter(pk=row.pk).update(tags=[tag_val])


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0025_alter_lat_lon_decimal_precision'),
    ]

    operations = [
        migrations.AddField(
            model_name='review',
            name='tags',
            field=models.JSONField(
                default=list,
                help_text='List of ReviewTag values (at least one)',
                verbose_name='Review tags',
            ),
        ),
        migrations.RunPython(copy_tag_to_tags, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='review',
            name='tag',
        ),
        migrations.CreateModel(
            name='ReviewImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='review_images/', verbose_name='Image')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created at')),
                (
                    'review',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='images',
                        to='order.review',
                        verbose_name='Review',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Review image',
                'verbose_name_plural': 'Review images',
                'ordering': ['id'],
            },
        ),
    ]
