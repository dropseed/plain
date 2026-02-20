# Generated manually

import plain.api.models
from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainapi", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceGrant",
            fields=[
                ("id", models.PrimaryKeyField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "device_code",
                    models.CharField(
                        default=plain.api.models.generate_device_code, max_length=64
                    ),
                ),
                (
                    "user_code",
                    models.CharField(
                        default=plain.api.models.generate_user_code, max_length=9
                    ),
                ),
                ("status", models.CharField(default="pending", max_length=20)),
                ("scope", models.CharField(max_length=500, required=False)),
                ("expires_at", models.DateTimeField()),
                ("interval", models.IntegerField(default=5)),
                (
                    "api_key",
                    models.ForeignKeyField(
                        allow_null=True,
                        on_delete=models.SET_NULL,
                        required=False,
                        to="plainapi.APIKey",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="devicegrant",
            constraint=models.UniqueConstraint(
                fields=("device_code",),
                name="plainapi_devicegrant_unique_device_code",
            ),
        ),
        migrations.AddConstraint(
            model_name="devicegrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="pending"),
                fields=("user_code",),
                name="plainapi_devicegrant_unique_pending_user_code",
            ),
        ),
    ]
