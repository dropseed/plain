import uuid

from plain import models
from plain.models import migrations


def set_uuids(models, schema_editor):
    Car = models.get_model("examples", "Car")
    for sq in Car.objects.filter(uuid__isnull=True):
        sq.uuid = uuid.uuid4()
        sq.save(clean_and_validate=False)


class Migration(migrations.Migration):
    dependencies = [
        ("examples", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="car",
            name="uuid",
            field=models.UUIDField(allow_null=True),
        ),
        migrations.RunPython(set_uuids),
        migrations.RemoveField(
            model_name="car",
            name="uuid",
        ),
    ]
