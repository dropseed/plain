# Generated by Plain 5.0.dev20231127233940 on 2023-12-22 03:47

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CacheItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                    ),
                ),
                ("key", models.CharField(max_length=255, unique=True)),
                ("value", models.JSONField(required=False, null=True)),
                (
                    "expires_at",
                    models.DateTimeField(required=False, db_index=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
