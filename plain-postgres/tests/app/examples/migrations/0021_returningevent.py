from plain.postgres import migrations

from plain import postgres


class Migration(migrations.Migration):
    dependencies = (("examples", "0020_stringconditionsexample"),)

    operations = (
        migrations.CreateModel(
            name="ReturningEvent",
            fields=[
                ("id", postgres.PrimaryKeyField()),
                ("count", postgres.IntegerField(default=0)),
                ("label", postgres.TextField(max_length=100)),
                ("payload", postgres.JSONField(allow_null=True, required=False)),
            ],
        ),
    )
