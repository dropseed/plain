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
                        primary_key=True,
                    ),
                ),
                ("session_data", models.TextField()),
                (
                    "expire_date",
                    models.DateTimeField(),
                ),
            ],
            managers=[
                ("objects", plain.sessions.models.SessionManager()),
            ],
        ),
    ]
