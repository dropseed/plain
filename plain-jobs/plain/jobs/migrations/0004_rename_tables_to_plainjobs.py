# Manual transition from plain-worker (plainworker) to plain-jobs (plainjobs)
#
# If upgrading from plain.worker, run this SQL command BEFORE running migrations:
#
# plain db shell -- -c "INSERT INTO plainmigrations (app, name, applied) SELECT 'plainjobs', name, applied FROM plainmigrations WHERE app = 'plainworker' ON CONFLICT DO NOTHING;"
#
# Then run: plain migrate
# Then run: plain migrations prune (to clean up old plainworker records)
#
# Step 1: Rename tables from plainworker_* to plainjobs_*

from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainjobs", "0003_rename_job_jobprocess_and_more"),
    ]

    operations = [
        migrations.AlterModelTable(
            name="JobRequest",
            table="plainjobs_jobrequest",
        ),
        migrations.AlterModelTable(
            name="JobProcess",
            table="plainjobs_jobprocess",
        ),
        migrations.AlterModelTable(
            name="JobResult",
            table="plainjobs_jobresult",
        ),
    ]
