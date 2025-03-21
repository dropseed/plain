# Generated by Plain 5.0.dev20240109225803 on 2024-01-09 23:17

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainworker", "0009_alter_jobresult_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="jobresult",
            name="status",
            field=models.CharField(
                required=False,
                choices=[
                    ("", "Unknown"),
                    ("PROCESSING", "Processing"),
                    ("SUCCESSFUL", "Successful"),
                    ("ERRORED", "Errored"),
                    ("LOST", "Lost"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]
