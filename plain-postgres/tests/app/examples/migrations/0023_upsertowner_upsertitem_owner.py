from plain.postgres import migrations

from plain import postgres


class Migration(migrations.Migration):
    dependencies = (("examples", "0022_upsertitem"),)

    operations = (
        migrations.CreateModel(
            name="UpsertOwner",
            fields=[
                ("id", postgres.PrimaryKeyField()),
                ("name", postgres.TextField(max_length=100)),
            ],
        ),
        migrations.AddField(
            model_name="upsertitem",
            name="owner",
            field=postgres.ForeignKeyField(
                allow_null=True, on_delete=postgres.CASCADE, to="examples.upsertowner"
            ),
        ),
        migrations.AddField(
            model_name="upsertitem",
            name="created_at",
            field=postgres.DateTimeField(create_now=True),
        ),
        migrations.AddField(
            model_name="upsertitem",
            name="updated_at",
            field=postgres.DateTimeField(create_now=True, update_now=True),
        ),
    )
