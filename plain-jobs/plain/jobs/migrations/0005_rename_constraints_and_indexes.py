# Step 2: Rename constraints and indexes from plainworker_* to plainjobs_*
# (Tables were renamed to plainjobs_* in migration 0004)

from plain import models
from plain.models import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("plainjobs", "0004_rename_tables_to_plainjobs"),
    ]

    operations = [
        # Remove old constraints (on plainjobs_* tables now)
        migrations.RemoveConstraint(
            model_name="jobprocess",
            name="plainworker_job_unique_uuid",
        ),
        migrations.RemoveConstraint(
            model_name="jobrequest",
            name="plainworker_jobrequest_unique_job_class_key",
        ),
        migrations.RemoveConstraint(
            model_name="jobrequest",
            name="plainworker_jobrequest_unique_uuid",
        ),
        migrations.RemoveConstraint(
            model_name="jobresult",
            name="plainworker_jobresult_unique_uuid",
        ),
        # Rename indexes
        migrations.RenameIndex(
            model_name="jobprocess",
            new_name="plainjobs_j_created_04fbb8_idx",
            old_name="plainworker_created_0d3928_idx",
        ),
        migrations.RenameIndex(
            model_name="jobprocess",
            new_name="plainjobs_j_queue_d07d21_idx",
            old_name="plainworker_queue_2550ba_idx",
        ),
        migrations.RenameIndex(
            model_name="jobprocess",
            new_name="plainjobs_j_unique__67172c_idx",
            old_name="plainworker_unique__9dc0bb_idx",
        ),
        migrations.RenameIndex(
            model_name="jobprocess",
            new_name="plainjobs_j_started_5cd62a_idx",
            old_name="plainworker_started_b80ec5_idx",
        ),
        migrations.RenameIndex(
            model_name="jobprocess",
            new_name="plainjobs_j_job_cla_19f3c1_idx",
            old_name="plainworker_job_cla_fe2b70_idx",
        ),
        migrations.RenameIndex(
            model_name="jobprocess",
            new_name="plainjobs_j_job_req_32b6eb_idx",
            old_name="plainworker_job_req_357898_idx",
        ),
        migrations.RenameIndex(
            model_name="jobprocess",
            new_name="plainjobs_j_trace_i_9f93c8_idx",
            old_name="plainworker_trace_i_da2cfa_idx",
        ),
        migrations.RenameIndex(
            model_name="jobrequest",
            new_name="plainjobs_j_priorit_fd4fac_idx",
            old_name="plainworker_priorit_785e73_idx",
        ),
        migrations.RenameIndex(
            model_name="jobrequest",
            new_name="plainjobs_j_created_1eeb20_idx",
            old_name="plainworker_created_c81fe5_idx",
        ),
        migrations.RenameIndex(
            model_name="jobrequest",
            new_name="plainjobs_j_queue_b34b5a_idx",
            old_name="plainworker_queue_2614aa_idx",
        ),
        migrations.RenameIndex(
            model_name="jobrequest",
            new_name="plainjobs_j_start_a_f3b8da_idx",
            old_name="plainworker_start_a_4d6020_idx",
        ),
        migrations.RenameIndex(
            model_name="jobrequest",
            new_name="plainjobs_j_unique__42f6a6_idx",
            old_name="plainworker_unique__21a534_idx",
        ),
        migrations.RenameIndex(
            model_name="jobrequest",
            new_name="plainjobs_j_job_cla_a18abf_idx",
            old_name="plainworker_job_cla_3e7dea_idx",
        ),
        migrations.RenameIndex(
            model_name="jobrequest",
            new_name="plainjobs_j_trace_i_194003_idx",
            old_name="plainworker_trace_i_e9dfc5_idx",
        ),
        migrations.RenameIndex(
            model_name="jobresult",
            new_name="plainjobs_j_created_7978bf_idx",
            old_name="plainworker_created_6894c5_idx",
        ),
        migrations.RenameIndex(
            model_name="jobresult",
            new_name="plainjobs_j_job_pro_751a64_idx",
            old_name="plainworker_job_pro_ceabfb_idx",
        ),
        migrations.RenameIndex(
            model_name="jobresult",
            new_name="plainjobs_j_started_6fb2ce_idx",
            old_name="plainworker_started_9bce76_idx",
        ),
        migrations.RenameIndex(
            model_name="jobresult",
            new_name="plainjobs_j_ended_a_648f25_idx",
            old_name="plainworker_ended_a_63caaf_idx",
        ),
        migrations.RenameIndex(
            model_name="jobresult",
            new_name="plainjobs_j_status_1ef683_idx",
            old_name="plainworker_status_a7ca35_idx",
        ),
        migrations.RenameIndex(
            model_name="jobresult",
            new_name="plainjobs_j_job_req_3ddecf_idx",
            old_name="plainworker_job_req_1e1bf2_idx",
        ),
        migrations.RenameIndex(
            model_name="jobresult",
            new_name="plainjobs_j_job_cla_8791b4_idx",
            old_name="plainworker_job_cla_d138b5_idx",
        ),
        migrations.RenameIndex(
            model_name="jobresult",
            new_name="plainjobs_j_queue_0a2178_idx",
            old_name="plainworker_queue_23d8fe_idx",
        ),
        migrations.RenameIndex(
            model_name="jobresult",
            new_name="plainjobs_j_trace_i_02f370_idx",
            old_name="plainworker_trace_i_00c75f_idx",
        ),
        # Add new constraints (on plainworker_* tables, but with new names)
        migrations.AddConstraint(
            model_name="jobprocess",
            constraint=models.UniqueConstraint(
                fields=("uuid",), name="plainjobs_job_unique_uuid"
            ),
        ),
        migrations.AddConstraint(
            model_name="jobrequest",
            constraint=models.UniqueConstraint(
                condition=models.Q(("retry_attempt", 0), ("unique_key__gt", "")),
                fields=("job_class", "unique_key"),
                name="plainjobs_jobrequest_unique_job_class_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="jobrequest",
            constraint=models.UniqueConstraint(
                fields=("uuid",), name="plainjobs_jobrequest_unique_uuid"
            ),
        ),
        migrations.AddConstraint(
            model_name="jobresult",
            constraint=models.UniqueConstraint(
                fields=("uuid",), name="plainjobs_jobresult_unique_uuid"
            ),
        ),
    ]
