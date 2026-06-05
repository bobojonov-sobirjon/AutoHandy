from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0022_customuser_workshop_compliance'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailverificationtoken',
            name='code',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Numeric code entered in the app (e.g. 4 digits).',
                max_length=10,
                verbose_name='Verification code',
            ),
        ),
        migrations.AddIndex(
            model_name='emailverificationtoken',
            index=models.Index(fields=['user', 'code', 'is_used'], name='accounts_em_user_co_91a2b1_idx'),
        ),
    ]
