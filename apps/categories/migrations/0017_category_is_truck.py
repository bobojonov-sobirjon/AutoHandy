from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('categories', '0016_seed_towing_entry_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='is_truck',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'If True: category is for Emergency Roadside / services for semi trucks only '
                    '(tire, jump start, fuel, lockout, repair, towing). Use is_truck=true in the API to list truck catalog.'
                ),
                verbose_name='Semi-truck service',
            ),
        ),
    ]
