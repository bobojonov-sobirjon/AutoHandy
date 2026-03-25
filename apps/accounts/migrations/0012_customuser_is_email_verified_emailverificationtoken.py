# Generated manually for email verification flow

import uuid
from django.conf import settings
from django.db import migrations, models
from django.db.models import F
import django.db.models.deletion


def copy_is_verified_to_is_email_verified(apps, schema_editor):
    CustomUser = apps.get_model('accounts', 'CustomUser')
    CustomUser.objects.update(is_email_verified=F('is_verified'))


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_alter_carowner_options_alter_faq_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='is_email_verified',
            field=models.BooleanField(
                default=False,
                help_text='Set true after the user confirms email via verification link.',
                verbose_name='Email verified (profile flow)',
            ),
        ),
        migrations.CreateModel(
            name='EmailVerificationToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ('email', models.EmailField(max_length=254, verbose_name='Email to verify')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('is_used', models.BooleanField(default=False)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='email_verification_tokens',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='User',
                )),
            ],
            options={
                'verbose_name': 'Email verification token',
                'verbose_name_plural': 'Email verification tokens',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='emailverificationtoken',
            index=models.Index(fields=['token', 'is_used'], name='accounts_em_token_i_7f8e9a_idx'),
        ),
        migrations.RunPython(copy_is_verified_to_is_email_verified, migrations.RunPython.noop),
    ]
