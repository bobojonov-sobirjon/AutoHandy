# Generated manually for chat messaging lifecycle

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0003_alter_chatmessage_options_alter_chatroom_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatroom',
            name='is_active',
            field=models.BooleanField(
                default=True,
                help_text='When false, participants can read history but cannot send new messages.',
                verbose_name='Messaging active',
            ),
        ),
        migrations.AddField(
            model_name='chatroom',
            name='closes_at',
            field=models.DateTimeField(
                blank=True,
                help_text='After order completion: grace period end (default +2h). Then is_active becomes false.',
                null=True,
                verbose_name='Messaging closes at',
            ),
        ),
        migrations.AlterField(
            model_name='chatmessage',
            name='sender',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name='sent_messages',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Sender',
            ),
        ),
        migrations.AddField(
            model_name='chatmessage',
            name='is_system',
            field=models.BooleanField(
                default=False,
                help_text='Platform-generated message (safety, warnings, conversation closed).',
                verbose_name='System message',
            ),
        ),
        migrations.AddField(
            model_name='chatmessage',
            name='system_code',
            field=models.CharField(
                blank=True,
                default='',
                max_length=64,
                verbose_name='System message code',
            ),
        ),
        migrations.AlterField(
            model_name='chatmessage',
            name='message_type',
            field=models.CharField(
                choices=[
                    ('text', 'Text'),
                    ('image', 'Image'),
                    ('file', 'File'),
                    ('audio', 'Audio'),
                    ('system', 'System'),
                ],
                default='text',
                max_length=10,
                verbose_name='Message type',
            ),
        ),
    ]
