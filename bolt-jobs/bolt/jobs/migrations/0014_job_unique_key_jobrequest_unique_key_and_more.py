# Generated by Bolt 5.0.dev20240117193239 on 2024-01-17 19:41

from bolt.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("boltqueue", "0013_alter_job_options_alter_jobresult_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="unique_key",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddField(
            model_name="jobrequest",
            name="unique_key",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddField(
            model_name="jobresult",
            name="unique_key",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddIndex(
            model_name="job",
            index=models.Index(
                fields=["job_class", "unique_key"], name="job_class_unique_key"
            ),
        ),
        migrations.AddIndex(
            model_name="jobrequest",
            index=models.Index(
                fields=["job_class", "unique_key"], name="job_request_class_unique_key"
            ),
        ),
    ]
