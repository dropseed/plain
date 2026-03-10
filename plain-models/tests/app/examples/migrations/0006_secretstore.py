# Generated manually for encrypted field tests

from plain import models
from plain.models import migrations
from plain.models.fields.encrypted import (
    EncryptedJSONField,
    EncryptedTextField,
)


class Migration(migrations.Migration):
    dependencies = [
        ("examples", "0005_feature_carfeature_car_features"),
    ]

    operations = [
        migrations.CreateModel(
            name="SecretStore",
            fields=[
                ("id", models.PrimaryKeyField()),
                ("name", models.CharField(max_length=100)),
                ("api_key", EncryptedTextField(max_length=200)),
                ("notes", EncryptedTextField(required=False)),
                ("config", EncryptedJSONField(allow_null=True, required=False)),
            ],
        ),
    ]
