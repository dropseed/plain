# Generated by Plain 5.0.dev20240109233227 on 2024-01-10 00:25

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainworker", "0010_alter_jobresult_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobrequest",
            name="retries",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="jobrequest",
            name="retry_attempt",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="jobrequest",
            name="start_at",
            field=models.DateTimeField(required=False, allow_null=True),
        ),
        migrations.AddField(
            model_name="jobresult",
            name="retries",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="jobresult",
            name="retry_attempt",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="jobresult",
            name="retry_job_request_uuid",
            field=models.UUIDField(required=False, allow_null=True),
        ),
    ]
