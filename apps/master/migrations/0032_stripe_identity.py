# Generated manually for Stripe Identity on Master

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0031_stripe_and_payment'),
    ]

    operations = [
        migrations.AddField(
            model_name='master',
            name='stripe_identity_verification_session_id',
            field=models.CharField(
                blank=True,
                default='',
                help_text='vs_… — document/selfie verification session (no PII stored locally).',
                max_length=128,
                verbose_name='Stripe Identity verification session id',
            ),
        ),
        migrations.AddField(
            model_name='master',
            name='identity_verification_status',
            field=models.CharField(
                choices=[
                    ('not_started', 'Not started'),
                    ('pending', 'Pending'),
                    ('verified', 'Verified'),
                    ('requires_input', 'Requires input'),
                    ('canceled', 'Canceled'),
                    ('failed', 'Failed'),
                ],
                default='not_started',
                max_length=32,
                verbose_name='Identity verification status',
            ),
        ),
        migrations.AddField(
            model_name='master',
            name='identity_verified_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Identity verified at'),
        ),
        migrations.AddField(
            model_name='master',
            name='identity_last_error_code',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Stripe error code only — no document or SSN data.',
                max_length=64,
                verbose_name='Identity last error code',
            ),
        ),
    ]
