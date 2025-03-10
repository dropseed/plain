# Generated by Plain 5.0.dev20231226225312 on 2023-12-28 19:28

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainworker", "0002_jobresult_remove_jobrequest_completed_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobresult",
            name="status",
            field=models.CharField(
                choices=[
                    ("PROCESSING", "Processing"),
                    ("SUCCESSFUL", "Successful"),
                    ("ERRORED", "Errored"),
                ],
                default="PROCESSING",
                max_length=20,
            ),
        ),
    ]
