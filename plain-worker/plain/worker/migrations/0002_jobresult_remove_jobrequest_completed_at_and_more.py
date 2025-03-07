# Generated by Plain 5.0.dev20231226225312 on 2023-12-28 19:18

import uuid

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainworker", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="JobResult",
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
                    models.UUIDField(default=uuid.uuid4, unique=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "started_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "completed_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("error", models.TextField(blank=True)),
                ("job_request_uuid", models.UUIDField(db_index=True)),
                ("job_class", models.CharField(db_index=True, max_length=255)),
                ("parameters", models.JSONField(blank=True, null=True)),
                ("priority", models.IntegerField(db_index=True, default=0)),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.RemoveField(
            model_name="jobrequest",
            name="completed_at",
        ),
        migrations.RemoveField(
            model_name="jobrequest",
            name="error",
        ),
        migrations.RemoveField(
            model_name="jobrequest",
            name="started_at",
        ),
        migrations.RemoveField(
            model_name="jobrequest",
            name="updated_at",
        ),
    ]
