# Generated by Plain 5.0.dev20231228220106 on 2023-12-28 22:35

from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainworker", "0003_jobresult_status"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="jobresult",
            options={"ordering": ["-started_at"]},
        ),
    ]
