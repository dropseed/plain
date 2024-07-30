import plain.sessions.models
from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Session",
            fields=[
                (
                    "session_key",
                    models.CharField(
                        max_length=40,
                        serialize=False,
                        primary_key=True,
                    ),
                ),
                ("session_data", models.TextField()),
                (
                    "expire_date",
                    models.DateTimeField(db_index=True),
                ),
            ],
            options={
                "abstract": False,
            },
            managers=[
                ("objects", plain.sessions.models.SessionManager()),
            ],
        ),
    ]
