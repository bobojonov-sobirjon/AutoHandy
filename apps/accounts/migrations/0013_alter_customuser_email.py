from django.db import migrations, models


def empty_string_email_to_null(apps, schema_editor):
    CustomUser = apps.get_model('accounts', 'CustomUser')
    CustomUser.objects.filter(email='').update(email=None)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_customuser_is_email_verified_emailverificationtoken'),
    ]

    operations = [
        migrations.RunPython(empty_string_email_to_null, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='customuser',
            name='email',
            field=models.EmailField(
                blank=True,
                help_text='Optional until set via profile. Phone-only users may have no email.',
                max_length=254,
                null=True,
                unique=True,
                verbose_name='Email',
            ),
        ),
    ]
