import plain.passwords.models
import plain.passwords.validators
from plain import postgres
from plain.postgres import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
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
    ]
