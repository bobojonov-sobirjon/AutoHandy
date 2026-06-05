from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0021_stripe_and_payment'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='has_tools_confirmed',
            field=models.BooleanField(
                default=False,
                help_text='Master confirms they have the tools needed for offered services.',
                verbose_name='Required tools confirmed',
            ),
        ),
        migrations.AddField(
            model_name='customuser',
            name='has_licenses_confirmed',
            field=models.BooleanField(
                default=False,
                help_text='Master confirms they hold legally required licenses, if any.',
                verbose_name='Required licenses confirmed',
            ),
        ),
        migrations.AddField(
            model_name='customuser',
            name='workshop_compliance_confirmed_at',
            field=models.DateTimeField(
                blank=True,
                help_text='Set when tools and licenses confirmations are saved via profile API.',
                null=True,
                verbose_name='Workshop compliance confirmed at',
            ),
        ),
    ]
