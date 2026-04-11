# Drop review images (photos belong on work-completion endpoint only)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0026_review_tags_json_reviewimage'),
    ]

    operations = [
        migrations.DeleteModel(
            name='ReviewImage',
        ),
    ]
