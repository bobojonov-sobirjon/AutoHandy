import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('categories', '0008_alter_category_options_alter_category_created_at_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='category',
            name='service_type',
        ),
        migrations.AddField(
            model_name='category',
            name='parent',
            field=models.ForeignKey(
                blank=True,
                help_text='Optional parent to group related categories (e.g. same service family across by_order / by_master).',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='children',
                to='categories.category',
                verbose_name='Parent category',
            ),
        ),
    ]
