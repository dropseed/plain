# Generated by Bolt 5.0.dev20240202214502 on 2024-02-05 02:33

from bolt.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0001_squashed"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="is_superuser",
        ),
    ]