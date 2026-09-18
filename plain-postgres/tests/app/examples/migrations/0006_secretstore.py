# Generated manually for encrypted field tests

from plain.postgres import migrations
from plain.postgres.fields.encrypted import (
    EncryptedJSONField,
    EncryptedTextField,
)

from plain import postgres


class Migration(migrations.Migration):
    dependencies = (("examples", "0005_feature_carfeature_car_features"),)

    operations = (
        migrations.CreateModel(
            name="SecretStore",
            fields=[
                ("id", postgres.PrimaryKeyField()),
                ("name", postgres.TextField(max_length=100)),
                ("api_key", EncryptedTextField(max_length=200)),
                ("notes", EncryptedTextField(required=False)),
                ("config", EncryptedJSONField(allow_null=True, required=False)),
            ],
        ),
    )
