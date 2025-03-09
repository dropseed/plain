# Generated by Plain 0.31.0 on 2025-03-08 21:33

import uuid

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainworker", "0018_jobrequest_unique_job_class_unique_key"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="jobrequest",
            name="unique_job_class_unique_key",
        ),
        migrations.AlterField(
            model_name="job",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4),
        ),
        migrations.AlterField(
            model_name="jobrequest",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4),
        ),
        migrations.AlterField(
            model_name="jobresult",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4),
        ),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.UniqueConstraint(
                fields=("uuid",), name="plainworker_job_unique_uuid"
            ),
        ),
        migrations.AddConstraint(
            model_name="jobrequest",
            constraint=models.UniqueConstraint(
                condition=models.Q(("retry_attempt", 0), ("unique_key__gt", "")),
                fields=("job_class", "unique_key"),
                name="plainworker_jobrequest_unique_job_class_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="jobrequest",
            constraint=models.UniqueConstraint(
                fields=("uuid",), name="plainworker_jobrequest_unique_uuid"
            ),
        ),
        migrations.AddConstraint(
            model_name="jobresult",
            constraint=models.UniqueConstraint(
                fields=("uuid",), name="plainworker_jobresult_unique_uuid"
            ),
        ),
    ]
