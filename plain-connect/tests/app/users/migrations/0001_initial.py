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
                ("username", postgres.TextField(max_length=255)),
            ],
        ),
    ]
