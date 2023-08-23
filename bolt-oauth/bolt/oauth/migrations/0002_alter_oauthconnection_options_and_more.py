# Generated by Bolt 4.0.3 on 2022-03-18 18:24

from bolt.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boltoauth", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="oauthconnection",
            options={"ordering": ("provider_key",), "verbose_name": "OAuth Connection"},
        ),
        migrations.AlterField(
            model_name="oauthconnection",
            name="access_token",
            field=models.CharField(max_length=100),
        ),
    ]
