from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('chat', '0003_alter_chatmessage_options_alter_chatroom_options_and_more'),
        ('order', '0034_alter_order_custom_request_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='chat_room',
            field=models.ForeignKey(
                blank=True,
                help_text='Auto-created on accept: master (initiator) ↔ user (receiver).',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='orders',
                to='chat.chatroom',
                verbose_name='Chat room',
            ),
        ),
    ]

