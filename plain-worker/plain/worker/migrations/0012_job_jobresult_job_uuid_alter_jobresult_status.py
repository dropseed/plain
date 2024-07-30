# Generated by Plain 5.0.dev20240114170303 on 2024-01-17 18:45

import uuid

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainworker", "0011_jobrequest_retries_jobrequest_retry_attempt_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Job",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "uuid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "started_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("job_request_uuid", models.UUIDField(db_index=True)),
                ("job_class", models.CharField(db_index=True, max_length=255)),
                ("parameters", models.JSONField(blank=True, null=True)),
                ("priority", models.IntegerField(db_index=True, default=0)),
                ("source", models.TextField(blank=True)),
                ("retries", models.IntegerField(default=0)),
                ("retry_attempt", models.IntegerField(default=0)),
            ],
        ),
        migrations.AddField(
            model_name="jobresult",
            name="job_uuid",
            field=models.UUIDField(db_index=True, default=uuid.uuid4),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="jobresult",
            name="status",
            field=models.CharField(
                choices=[
                    ("SUCCESSFUL", "Successful"),
                    ("ERRORED", "Errored"),
                    ("LOST", "Lost"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
