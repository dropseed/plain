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
                ("email", postgres.EmailField(max_length=254)),
            ],
        ),
    ]
