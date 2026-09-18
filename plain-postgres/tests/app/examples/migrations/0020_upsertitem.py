from plain.postgres import migrations

from plain import postgres


class Migration(migrations.Migration):
    dependencies = (("examples", "0019_returningevent"),)

    operations = (
        migrations.CreateModel(
            name="UpsertItem",
            fields=[
                ("id", postgres.PrimaryKeyField()),
                ("key", postgres.TextField(max_length=100)),
                ("label", postgres.TextField(default="")),
                ("value", postgres.IntegerField(default=0)),
            ],
        ),
    )
