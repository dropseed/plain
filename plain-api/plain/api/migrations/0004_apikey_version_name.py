# Generated by Plain 0.37.0 on 2025-04-09 04:19

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainapi", "0003_alter_apikey_token_alter_apikey_uuid_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="apikey",
            name="version_name",
            field=models.CharField(max_length=255, required=False),
        ),
    ]
