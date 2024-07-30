# Generated by Plain 5.0.dev20240114170303 on 2024-01-17 19:24

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainworker", "0012_job_jobresult_job_uuid_alter_jobresult_status"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="job",
            options={"ordering": ["-created_at"]},
        ),
        migrations.AlterModelOptions(
            name="jobresult",
            options={"ordering": ["-created_at"]},
        ),
        migrations.AlterField(
            model_name="job",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AlterField(
            model_name="jobrequest",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AlterField(
            model_name="jobresult",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
    ]
