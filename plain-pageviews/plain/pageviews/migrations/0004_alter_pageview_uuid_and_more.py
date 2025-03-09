# Generated by Plain 0.31.0 on 2025-03-08 21:33

import uuid

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainpageviews", "0003_alter_pageview_uuid"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pageview",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4),
        ),
        migrations.AddConstraint(
            model_name="pageview",
            constraint=models.UniqueConstraint(
                fields=("uuid",), name="plainpageviews_pageview_unique_uuid"
            ),
        ),
    ]
