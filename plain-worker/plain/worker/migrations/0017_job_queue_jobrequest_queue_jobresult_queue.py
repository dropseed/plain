# Generated by Plain 5.0.dev20240321171720 on 2024-03-21 18:47

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainworker", "0016_remove_job_worker_uuid_remove_jobresult_worker_uuid"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="queue",
            field=models.CharField(default="default", max_length=255),
        ),
        migrations.AddField(
            model_name="jobrequest",
            name="queue",
            field=models.CharField(default="default", max_length=255),
        ),
        migrations.AddField(
            model_name="jobresult",
            name="queue",
            field=models.CharField(default="default", max_length=255),
        ),
    ]
