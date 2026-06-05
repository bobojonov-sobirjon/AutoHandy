from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('categories', '0014_seed_custom_request_entry_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='is_towing_entry',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'If True: drivers see this as the client-only Towing entry; masters never see it in '
                    'the public category catalog. Attach this main category to towing orders server-side.'
                ),
                verbose_name='Towing entry',
            ),
        ),
    ]
