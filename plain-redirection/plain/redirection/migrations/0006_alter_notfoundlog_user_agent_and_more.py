# Generated by Plain 0.21.1 on 2025-02-06 16:48

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainredirection", "0005_alter_notfoundlog_referer_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notfoundlog",
            name="user_agent",
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AlterField(
            model_name="redirectlog",
            name="user_agent",
            field=models.CharField(blank=True, max_length=512),
        ),
    ]
