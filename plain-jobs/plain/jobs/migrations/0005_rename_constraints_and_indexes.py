# Step 2: Rename constraints and indexes from plainworker_* to plainjobs_*
# (Tables were renamed to plainjobs_* in migration 0004)

from plain.postgres import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainjobs", "0004_rename_tables_to_plainjobs"),
    ]

    operations = []
