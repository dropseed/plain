# Generated by Bolt 5.0.dev20230814020017 on 2023-08-14 02:09

from bolt.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sessions", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="session",
            options={},
        ),
        migrations.AlterField(
            model_name="session",
            name="expire_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="session",
            name="session_data",
            field=models.TextField(),
        ),
        migrations.AlterField(
            model_name="session",
            name="session_key",
            field=models.CharField(max_length=40, primary_key=True, serialize=False),
        ),
    ]
