# Generated by Plain 0.21.1 on 2025-02-06 16:36

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainredirection", "0003_alter_redirect_from_pattern"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notfoundlog",
            name="referer",
            field=models.CharField(required=False, default=""),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="redirectlog",
            name="referer",
            field=models.CharField(required=False, default=""),
            preserve_default=False,
        ),
    ]
