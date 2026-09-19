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
                ("password", postgres.TextField(max_length=128)),
            ],
        ),
    )
