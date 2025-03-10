# Generated by Plain 5.0.dev20231223023818 on 2023-12-23 03:30

import uuid

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="JobRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                    ),
                ),
                (
                    "uuid",
                    models.UUIDField(default=uuid.uuid4),
                ),
                ("job_class", models.CharField(max_length=255)),
                ("parameters", models.JSONField(required=False, allow_null=True)),
                ("priority", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "started_at",
                    models.DateTimeField(required=False, allow_null=True),
                ),
                (
                    "completed_at",
                    models.DateTimeField(required=False, allow_null=True),
                ),
                ("error", models.TextField(required=False)),
            ],
            options={
                "ordering": ["priority", "-created_at"],
            },
        ),
    ]
