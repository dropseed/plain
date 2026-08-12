from plain.postgres import migrations

from plain import postgres


class Migration(migrations.Migration):
    dependencies = (("examples", "0017_random_string_token"),)

    operations = (
        migrations.CreateModel(
            name="StorageParametersExample",
            fields=[
                ("id", postgres.PrimaryKeyField()),
                ("name", postgres.TextField(max_length=100)),
            ],
        ),
    )
