import plain.passwords.models
import plain.passwords.validators
from plain.postgres import migrations

from plain import postgres


class Migration(migrations.Migration):
    initial = True

    dependencies = ()

    operations = (
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", postgres.PrimaryKeyField()),
                ("email", postgres.EmailField()),
                (
                    "password",
                    plain.passwords.models.PasswordField(
                        validators=[
                            plain.passwords.validators.MinimumLengthValidator(),
                            plain.passwords.validators.CommonPasswordValidator(),
                            plain.passwords.validators.NumericPasswordValidator(),
                        ]
                    ),
                ),
            ],
        ),
    )
