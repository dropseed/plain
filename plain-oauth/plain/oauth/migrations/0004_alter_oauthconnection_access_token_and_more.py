# Generated by Plain 5.0.dev20230806030948 on 2023-08-08 19:32

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainoauth", "0003_alter_oauthconnection_access_token_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="oauthconnection",
            name="access_token",
            field=models.CharField(max_length=2000),
        ),
        migrations.AlterField(
            model_name="oauthconnection",
            name="refresh_token",
            field=models.CharField(required=False, max_length=2000),
        ),
    ]
