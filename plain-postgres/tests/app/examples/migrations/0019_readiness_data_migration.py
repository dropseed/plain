from plain.postgres import migrations


def noop_backfill(models, schema_editor):
    """Does nothing — exists so tests have an all-RunPython migration whose
    pending state should warn, not gate, readiness."""


class Migration(migrations.Migration):
    dependencies = [
        ("examples", "0018_storageparametersexample"),
    ]

    operations = [
        migrations.RunPython(noop_backfill),
    ]
