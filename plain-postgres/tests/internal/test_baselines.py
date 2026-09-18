"""A baseline migration stands in for a package's deleted history.

The loader only observes records; the planner decides run / adopt / refuse
and marks a baseline to adopt as a record-only plan entry; migrate() records
it without running it. These tests stage each row of that table against the
real test database, where `examples` has its full history recorded and
`plaintemplates` has no migrations at all.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner
from plain.postgres import get_connection
from plain.postgres.cli.migrations import apply, list_migrations, prune
from plain.postgres.migrations.exceptions import (
    BadMigrationError,
    ResetBoundaryError,
    StaleMigrationRecordsError,
)
from plain.postgres.migrations.executor import MigrationExecutor
from plain.postgres.migrations.loader import MigrationLoader
from plain.postgres.migrations.migration import Migration
from plain.postgres.migrations.recorder import MigrationRecorder
from plain.postgres.migrations.writer import MigrationWriter
from plain.postgres.preflight.database import CheckPrunableMigrations

# The last migration the test database has recorded for `examples`, a name
# it retired, and a model whose table exists there.
SENTINEL = "0018_storageparametersexample"
A_RETIRED_NAME = "0017_random_string_token"
EXISTING_MODEL = "DefaultsExample"
BASELINE = ("examples", "0019_baseline")


def migration_source(
    *, dependencies: tuple[tuple[str, str], ...], operations: str = "()"
) -> str:
    return f"""\
from plain import postgres
from plain.postgres import migrations


class Migration(migrations.Migration):
    dependencies = {dependencies!r}
    operations = {operations}
"""


def recorded(package_label: str) -> list[str]:
    return sorted(
        name
        for label, name in MigrationRecorder(get_connection()).applied_migrations()
        if label == package_label
    )


def write_baseline(
    root: Path,
    label: str = "examples",
    name: str = "0019_baseline",
    *,
    supersedes: str = SENTINEL,
    model: str = EXISTING_MODEL,
    retired: list[str] | None = None,
    dependencies: str = "()",
) -> None:
    if retired is None:
        retired = recorded(label)
    (root / label / f"{name}.py").write_text(f"""\
from plain import postgres
from plain.postgres import migrations


class Migration(migrations.Migration):
    supersedes = {supersedes!r}
    retired = {tuple(retired)!r}
    shipped_in = "2.0"
    dependencies = {dependencies}
    operations = (
        migrations.CreateModel(
            name={model!r},
            fields=[("id", postgres.PrimaryKeyField())],
        ),
    )
""")


def column_exists(table: str, column: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            [table, column],
        )
        return cursor.fetchone() is not None


@pytest.fixture
def migrations_dir(temp_migrations: Callable[..., Path], db: None) -> Path:
    return temp_migrations("examples", "plaintemplates")


def test_sentinel_recorded_adopts_with_one_record_and_no_ddl(
    migrations_dir: Path, capture_queries
) -> None:
    write_baseline(migrations_dir)

    executor = MigrationExecutor(get_connection())
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    assert [m.name for m in plan] == ["0019_baseline"]
    assert executor.record_only == {BASELINE}

    with capture_queries() as queries:
        result = CliRunner().invoke(apply, ["--no-input"])

    assert result.exit_code == 0, result.output
    assert "examples.0019_baseline (baseline: recorded, not run)" in result.output
    assert "0019_baseline" in recorded("examples")
    assert not any("CREATE TABLE" in q["sql"] for q in queries)


def test_a_real_migration_after_a_pending_baseline_runs(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)
    (migrations_dir / "examples" / "0020_add_color.py").write_text(
        migration_source(
            dependencies=(BASELINE,),
            operations='(migrations.AddField(model_name="defaultsexample", name="color", field=postgres.TextField(default="")),)',
        )
    )

    result = CliRunner().invoke(apply, ["--no-input"])

    assert result.exit_code == 0, result.output
    assert {"0019_baseline", "0020_add_color"} <= set(recorded("examples"))
    assert column_exists("examples_defaultsexample", "color")


def test_fresh_package_runs_the_baseline(migrations_dir: Path) -> None:
    write_baseline(
        migrations_dir,
        "plaintemplates",
        "0001_baseline",
        supersedes="0000_gone",
        model="Thing",
        retired=[],
    )

    result = CliRunner().invoke(apply, ["--no-input"])

    assert result.exit_code == 0, result.output
    assert "0001_baseline" in recorded("plaintemplates")
    assert "plaintemplates_thing" in get_connection().table_names()
    assert "recorded, not run" not in result.output  # it ran


def test_sentinel_absent_refuses(migrations_dir: Path) -> None:
    write_baseline(migrations_dir, supersedes="0099_never_applied")

    executor = MigrationExecutor(get_connection())
    with pytest.raises(ResetBoundaryError) as excinfo:
        executor.migration_plan(executor.loader.graph.leaf_nodes())
    message = str(excinfo.value)
    assert "examples.0099_never_applied" in message
    assert "Upgrade through" in message

    result = CliRunner().invoke(apply, ["--no-input"])
    assert result.exit_code != 0
    assert message in result.output
    assert "Traceback" not in result.output

    refusals = [
        r
        for r in CheckPrunableMigrations().run()
        if r.id == "postgres.migration_history"
    ]
    assert [r.fix for r in refusals] == [message]
    assert not refusals[0].warning


def test_refusal_wins_over_history_validation(migrations_dir: Path) -> None:
    """An applied migration depending on a refused baseline must produce the
    refusal's message, not an inconsistent-history traceback."""
    write_baseline(migrations_dir)
    recorder = MigrationRecorder(get_connection())
    recorder.record_unapplied("examples", SENTINEL)
    (migrations_dir / "plaintemplates" / "0001_initial.py").write_text(
        migration_source(dependencies=(("examples", "0001_initial"),))
    )
    recorder.record_applied("plaintemplates", "0001_initial")

    result = CliRunner().invoke(apply, ["--no-input"])

    assert result.exit_code != 0
    assert "Upgrade through" in result.output
    assert "is applied before its dependency" not in result.output
    assert "Traceback" not in result.output


def test_fake_of_the_named_baseline_repairs_a_pruned_sentinel(
    migrations_dir: Path,
) -> None:
    write_baseline(migrations_dir)
    MigrationRecorder(get_connection()).record_unapplied("examples", SENTINEL)

    result = CliRunner().invoke(
        apply, ["examples", "0019_baseline", "--fake", "--no-input"]
    )

    assert result.exit_code == 0, result.output
    assert "0019_baseline" in recorded("examples")


def test_baseline_recorded_is_nothing_to_do(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)
    MigrationRecorder(get_connection()).record_applied(*BASELINE)

    executor = MigrationExecutor(get_connection())
    assert executor.migration_plan(executor.loader.graph.leaf_nodes()) == []
    assert executor.record_only == set()

    result = CliRunner().invoke(apply, ["--no-input"])
    assert result.exit_code == 0, result.output
    assert "No migrations to apply" in result.output


def test_records_without_tables_refuses(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)
    with get_connection().cursor() as cursor:
        for table in get_connection().table_names(cursor):
            if table.startswith("examples_"):
                cursor.execute(f'DROP TABLE "{table}" CASCADE')

    executor = MigrationExecutor(get_connection())
    with pytest.raises(StaleMigrationRecordsError) as excinfo:
        executor.migration_plan(executor.loader.graph.leaf_nodes())
    assert "examples_defaultsexample" in str(excinfo.value)
    assert "plain migrations prune examples" in str(excinfo.value)

    # The prescribed remedy works: drop the package's records, then the baseline runs.
    pruned = CliRunner().invoke(prune, ["examples", "--yes"])
    assert pruned.exit_code == 0, pruned.output
    assert recorded("examples") == []
    result = CliRunner().invoke(apply, ["--no-input"])
    assert result.exit_code == 0, result.output
    assert recorded("examples") == ["0019_baseline"]
    assert "examples_defaultsexample" in get_connection().table_names()


def test_targeted_apply_leaves_other_packages_alone(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)  # examples has a pending adoption

    check = CliRunner().invoke(apply, ["plaintemplates", "--check", "--no-input"])
    assert check.exit_code == 0, check.output

    result = CliRunner().invoke(apply, ["plaintemplates", "--no-input"])
    assert result.exit_code == 0, result.output
    assert "0019_baseline" not in recorded("examples")


def test_dependency_on_a_retired_name_resolves_to_the_baseline(
    migrations_dir: Path,
) -> None:
    write_baseline(migrations_dir)
    (migrations_dir / "examples" / "0020_next.py").write_text(
        migration_source(dependencies=(("examples", SENTINEL),))
    )

    loader = MigrationLoader(get_connection())

    parents = loader.graph.node_map[("examples", "0020_next")].parents
    assert {p.key for p in parents} == {BASELINE}
    # The edge is resolved; the migration's own dependencies stay as written,
    # so a loader over a candidate set can share these instances.
    migration = loader.graph.nodes[("examples", "0020_next")]
    assert migration is not None
    assert migration.dependencies == [("examples", SENTINEL)]


def test_applied_migration_on_a_pending_baseline_is_consistent(
    migrations_dir: Path,
) -> None:
    write_baseline(migrations_dir)
    (migrations_dir / "examples" / "0020_next.py").write_text(
        migration_source(dependencies=(("examples", SENTINEL),))
    )
    MigrationRecorder(get_connection()).record_applied("examples", "0020_next")

    loader = MigrationLoader(get_connection())
    loader.check_consistent_history(get_connection())  # does not raise

    result = CliRunner().invoke(apply, ["--no-input"])
    assert result.exit_code == 0, result.output
    assert "0019_baseline" in recorded("examples")
    assert "examples.0020_next" not in result.output  # not re-run


def test_check_reports_a_pending_adoption(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)

    result = CliRunner().invoke(apply, ["--plan", "--check", "--no-input"])

    assert result.exit_code == 1
    assert "examples.0019_baseline (baseline: recorded, not run)" in result.output
    assert "No planned migration operations" not in result.output


def test_two_baselines_in_one_package_is_an_error(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)
    write_baseline(migrations_dir, name="0021_baseline", retired=[])

    with pytest.raises(BadMigrationError, match="two baseline migrations"):
        MigrationLoader(None)


def test_superseded_migration_still_on_disk_is_an_error(migrations_dir: Path) -> None:
    write_baseline(migrations_dir, supersedes="0020_next")
    (migrations_dir / "examples" / "0020_next.py").write_text(
        migration_source(dependencies=())
    )

    with pytest.raises(BadMigrationError, match="still on disk"):
        MigrationLoader(None)


def test_retired_migration_still_on_disk_is_an_error(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)
    (migrations_dir / "examples" / f"{A_RETIRED_NAME}.py").write_text(
        migration_source(dependencies=())
    )

    with pytest.raises(BadMigrationError, match="still on disk"):
        MigrationLoader(None)


def test_baseline_named_like_a_retired_migration_is_an_error(
    migrations_dir: Path,
) -> None:
    write_baseline(migrations_dir, name="0001_initial")

    with pytest.raises(BadMigrationError, match="reuses a retired name"):
        MigrationLoader(None)


def test_prune_keeps_retired_records(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)
    before = recorded("examples")

    result = CliRunner().invoke(prune, ["--yes"])

    assert result.exit_code == 0, result.output
    assert "No orphan migration records found" in result.output
    assert recorded("examples") == before


def test_prunable_check_ignores_retired_records_and_prescribes_nothing(
    migrations_dir: Path,
) -> None:
    write_baseline(migrations_dir)  # retires every recorded examples migration
    MigrationRecorder(get_connection()).record_applied("examples", "0099_orphan")

    results = [
        r
        for r in CheckPrunableMigrations().run()
        if r.id == "postgres.prunable_migrations"
    ]

    assert len(results) == 1
    assert "Found 1 migration record with no file on disk" in results[0].fix
    assert "0099_orphan" in results[0].fix
    assert "prune" not in results[0].fix


def test_orphan_records_excludes_retired_names(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)
    recorder = MigrationRecorder(get_connection())
    recorder.record_applied("examples", "0099_orphan")

    loader = MigrationLoader(get_connection())

    assert loader.orphan_records(recorder.applied_migrations()) == [
        ("examples", "0099_orphan")
    ]


def test_writer_serializes_a_baseline() -> None:
    class Baseline(Migration):
        supersedes = SENTINEL
        retired = (A_RETIRED_NAME, SENTINEL)
        shipped_in = "2.0"
        dependencies = ()
        operations = ()

    source = MigrationWriter(Baseline("0019_baseline", "examples")).as_string()

    assert f"supersedes = {SENTINEL!r}" in source
    assert f"retired = ({A_RETIRED_NAME!r}, {SENTINEL!r})" in source
    assert "shipped_in = '2.0'" in source


def test_fake_repair_is_scoped_to_the_named_package(migrations_dir: Path) -> None:
    """Faking plaintemplates' own migration must not wave through a refusal
    in examples, even though plaintemplates depends on it."""
    write_baseline(migrations_dir)
    MigrationRecorder(get_connection()).record_unapplied("examples", SENTINEL)
    (migrations_dir / "plaintemplates" / "0001_initial.py").write_text(
        migration_source(dependencies=(("examples", "0001_initial"),))
    )

    result = CliRunner().invoke(
        apply, ["plaintemplates", "0001_initial", "--fake", "--no-input"]
    )

    assert result.exit_code != 0
    assert "Upgrade through" in result.output
    assert "0001_initial" not in recorded("plaintemplates")


def test_whole_plan_fake_advances_state_between_migrations(
    migrations_dir: Path,
) -> None:
    """--fake records without DDL; the second migration's state_forwards
    needs the model the first one declared."""
    (migrations_dir / "plaintemplates" / "0001_initial.py").write_text(
        migration_source(
            dependencies=(),
            operations='(migrations.CreateModel(name="Thing", fields=[("id", postgres.PrimaryKeyField())]),)',
        )
    )
    (migrations_dir / "plaintemplates" / "0002_color.py").write_text(
        migration_source(
            dependencies=(("plaintemplates", "0001_initial"),),
            operations='(migrations.AddField(model_name="thing", name="color", field=postgres.TextField(default="")),)',
        )
    )

    result = CliRunner().invoke(apply, ["plaintemplates", "--fake", "--no-input"])

    assert result.exit_code == 0, result.output
    assert recorded("plaintemplates") == ["0001_initial", "0002_color"]
    assert "plaintemplates_thing" not in get_connection().table_names()


def test_recorded_dependent_in_another_package_references_the_baseline_model(
    migrations_dir: Path,
) -> None:
    """The walk-through's failure: notes/tasks were recorded with FKs to
    users.User while users' baseline was still pending, and building project
    state blew up before the baseline's state ops ran."""
    write_baseline(migrations_dir)
    (migrations_dir / "plaintemplates" / "0001_initial.py").write_text(
        migration_source(
            dependencies=(("examples", SENTINEL),),
            operations=(
                '(migrations.CreateModel(name="Note", fields=['
                '("id", postgres.PrimaryKeyField()), '
                '("owner", postgres.ForeignKeyField(to="examples.defaultsexample", on_delete=postgres.CASCADE))'
                "]),)"
            ),
        )
    )
    MigrationRecorder(get_connection()).record_applied("plaintemplates", "0001_initial")

    result = CliRunner().invoke(apply, ["--no-input"])

    assert result.exit_code == 0, result.output
    assert "0019_baseline" in recorded("examples")


FK_DEPENDENT = (
    '(migrations.CreateModel(name="Note", fields=['
    '("id", postgres.PrimaryKeyField()), '
    '("owner", postgres.ForeignKeyField(to="examples.defaultsexample", on_delete=postgres.CASCADE))'
    "]),)"
)


def test_fake_repair_with_a_cross_package_fk_dependent(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)
    recorder = MigrationRecorder(get_connection())
    recorder.record_unapplied("examples", SENTINEL)
    (migrations_dir / "plaintemplates" / "0001_initial.py").write_text(
        migration_source(
            dependencies=(("examples", SENTINEL),), operations=FK_DEPENDENT
        )
    )
    recorder.record_applied("plaintemplates", "0001_initial")

    result = CliRunner().invoke(
        apply, ["examples", "0019_baseline", "--fake", "--no-input"]
    )

    assert result.exit_code == 0, result.output
    assert "0019_baseline" in recorded("examples")


def test_named_fake_of_a_later_migration_does_not_repair(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)
    MigrationRecorder(get_connection()).record_unapplied("examples", SENTINEL)
    (migrations_dir / "examples" / "0020_next.py").write_text(
        migration_source(dependencies=(BASELINE,))
    )

    result = CliRunner().invoke(
        apply, ["examples", "0020_next", "--fake", "--no-input"]
    )

    assert result.exit_code != 0
    assert "Upgrade through" in result.output
    assert "0019_baseline" not in recorded("examples")


def test_baseline_depending_on_a_retired_name_is_an_error(migrations_dir: Path) -> None:
    write_baseline(migrations_dir, dependencies=f'(("examples", "{SENTINEL}"),)')

    with pytest.raises(BadMigrationError, match="which it retires"):
        MigrationLoader(None)


def test_no_records_but_tables_refuses_with_a_choice(migrations_dir: Path) -> None:
    """A package whose records are all gone but whose tables remain: running
    the baseline would fail on the first CREATE TABLE, so the planner stops
    and says the two ways out. Named --fake of the baseline is one of them."""
    write_baseline(migrations_dir)
    recorder = MigrationRecorder(get_connection())
    for name in recorded("examples"):
        recorder.record_unapplied("examples", name)
    (migrations_dir / "plaintemplates" / "0001_initial.py").write_text(
        migration_source(dependencies=(("examples", SENTINEL),))
    )
    recorder.record_applied("plaintemplates", "0001_initial")

    result = CliRunner().invoke(apply, ["--no-input"])

    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "no migration records, but its tables exist" in result.output
    assert "apply examples 0019_baseline --fake" in result.output
    assert "0019_baseline" not in recorded("examples")

    repaired = CliRunner().invoke(
        apply, ["examples", "0019_baseline", "--fake", "--no-input"]
    )
    assert repaired.exit_code == 0, repaired.output
    assert recorded("examples") == ["0019_baseline"]


def test_pending_rename_of_the_only_table_does_not_look_stale(
    migrations_dir: Path,
) -> None:
    write_baseline(migrations_dir)
    (migrations_dir / "examples" / "0020_rename.py").write_text(
        migration_source(
            dependencies=(BASELINE,),
            operations='(migrations.AlterModelTable(name="defaultsexample", table="examples_defaults_renamed"),)',
        )
    )

    result = CliRunner().invoke(apply, ["--no-input"])

    assert result.exit_code == 0, result.output
    assert {"0019_baseline", "0020_rename"} <= set(recorded("examples"))
    assert "examples_defaults_renamed" in get_connection().table_names()


def test_prune_remedy_with_a_recorded_fk_dependent(migrations_dir: Path) -> None:
    """After `prune <pkg>` the baseline runs for real; a recorded migration
    elsewhere with an FK to its model must not break building the pre-run
    state (the walk-through's failure on `notes` -> `users.User`)."""
    write_baseline(migrations_dir)
    recorder = MigrationRecorder(get_connection())
    (migrations_dir / "plaintemplates" / "0001_initial.py").write_text(
        migration_source(
            dependencies=(("examples", SENTINEL),), operations=FK_DEPENDENT
        )
    )
    recorder.record_applied("plaintemplates", "0001_initial")
    with get_connection().cursor() as cursor:
        for table in get_connection().table_names(cursor):
            if table.startswith("examples_"):
                cursor.execute(f'DROP TABLE "{table}" CASCADE')
    for name in recorded("examples"):
        recorder.record_unapplied("examples", name)

    result = CliRunner().invoke(apply, ["--no-input"])

    assert result.exit_code == 0, result.output
    assert recorded("examples") == ["0019_baseline"]
    assert "examples_defaultsexample" in get_connection().table_names()


def test_fresh_baseline_with_an_fk_to_an_unapplied_migration(
    migrations_dir: Path,
) -> None:
    """A never-recorded baseline must not be preloaded into the pre-run state
    when nothing recorded depends on it - its own dependency may be
    unapplied, and preloading would reference a model that isn't there yet."""
    (migrations_dir / "examples" / "0019_gadget.py").write_text(
        migration_source(
            dependencies=(),
            operations='(migrations.CreateModel(name="Gadget", fields=[("id", postgres.PrimaryKeyField())]),)',
        )
    )
    (migrations_dir / "plaintemplates" / "0001_baseline.py").write_text("""\
from plain import postgres
from plain.postgres import migrations


class Migration(migrations.Migration):
    supersedes = "0000_gone"
    retired = ()
    shipped_in = "2.0"
    dependencies = (("examples", "0019_gadget"),)
    operations = (
        migrations.CreateModel(
            name="Note",
            fields=[
                ("id", postgres.PrimaryKeyField()),
                ("gadget", postgres.ForeignKeyField(to="examples.gadget", on_delete=postgres.CASCADE)),
            ],
        ),
    )
""")

    result = CliRunner().invoke(apply, ["--no-input"])

    assert result.exit_code == 0, result.output
    assert "0019_gadget" in recorded("examples")
    assert recorded("plaintemplates") == ["0001_baseline"]
    assert "plaintemplates_note" in get_connection().table_names()


def test_adopted_baseline_with_an_fk_to_an_unapplied_migration(
    migrations_dir: Path,
) -> None:
    """Adoption is record-only, but the baseline's state must still be built
    at its own turn - after the migration it depends on has run - not
    preloaded before anything runs."""
    (migrations_dir / "plaintemplates" / "0001_gadget.py").write_text(
        migration_source(
            dependencies=(),
            operations='(migrations.CreateModel(name="Gadget", fields=[("id", postgres.PrimaryKeyField())]),)',
        )
    )
    (migrations_dir / "examples" / "0019_baseline.py").write_text(f"""\
from plain import postgres
from plain.postgres import migrations


class Migration(migrations.Migration):
    supersedes = {SENTINEL!r}
    retired = {tuple(recorded("examples"))!r}
    shipped_in = "2.0"
    dependencies = (("plaintemplates", "0001_gadget"),)
    operations = (
        migrations.CreateModel(
            name={EXISTING_MODEL!r},
            fields=[
                ("id", postgres.PrimaryKeyField()),
                ("gadget", postgres.ForeignKeyField(to="plaintemplates.gadget", on_delete=postgres.CASCADE)),
            ],
        ),
    )
""")

    result = CliRunner().invoke(apply, ["--no-input"])

    assert result.exit_code == 0, result.output
    assert recorded("plaintemplates") == ["0001_gadget"]
    assert "0019_baseline" in recorded("examples")


def test_fake_repair_refuses_to_fake_anything_but_the_baseline(
    migrations_dir: Path,
) -> None:
    (migrations_dir / "plaintemplates" / "0001_gadget.py").write_text(
        migration_source(
            dependencies=(),
            operations='(migrations.CreateModel(name="Gadget", fields=[("id", postgres.PrimaryKeyField())]),)',
        )
    )
    write_baseline(migrations_dir, dependencies='(("plaintemplates", "0001_gadget"),)')
    MigrationRecorder(get_connection()).record_unapplied("examples", SENTINEL)

    result = CliRunner().invoke(
        apply, ["examples", "0019_baseline", "--fake", "--no-input"]
    )

    assert result.exit_code != 0
    assert "would also fake plaintemplates.0001_gadget" in result.output
    assert recorded("plaintemplates") == []
    assert "0019_baseline" not in recorded("examples")


def test_prune_rejects_an_unknown_package(migrations_dir: Path) -> None:
    result = CliRunner().invoke(prune, ["nosuchpackage", "--yes"])

    assert result.exit_code != 0
    assert "No installed app with label 'nosuchpackage'" in result.output


def test_retired_without_supersedes_is_an_error(migrations_dir: Path) -> None:
    (migrations_dir / "examples" / "0019_baseline.py").write_text(
        migration_source(dependencies=(("examples", SENTINEL),)).replace(
            "    dependencies", "    retired = ('0001_initial',)\n    dependencies"
        )
    )

    with pytest.raises(BadMigrationError, match="no `supersedes`"):
        MigrationLoader(get_connection())


def test_one_missing_table_is_stale_too(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)
    # A second model in the baseline, whose table stays put.
    path = migrations_dir / "examples" / "0019_baseline.py"
    path.write_text(
        path.read_text().replace(
            "    operations = (\n",
            "    operations = (\n"
            '        migrations.CreateModel(name="ConstraintExample", fields=[("id", postgres.PrimaryKeyField())]),\n',
            1,
        )
    )
    with get_connection().cursor() as cursor:
        cursor.execute('DROP TABLE "examples_defaultsexample" CASCADE')

    executor = MigrationExecutor(get_connection())
    with pytest.raises(StaleMigrationRecordsError) as excinfo:
        executor.migration_plan(executor.loader.graph.leaf_nodes())
    assert "some of its tables are missing (examples_defaultsexample)" in str(
        excinfo.value
    )


def test_list_annotates_adoptions_and_refusals(migrations_dir: Path) -> None:
    write_baseline(migrations_dir)

    result = CliRunner().invoke(list_migrations, ["examples"])
    assert result.exit_code == 0, result.output
    assert "[ ] 0019_baseline (baseline: will be recorded, not run)" in result.output

    MigrationRecorder(get_connection()).record_unapplied("examples", SENTINEL)
    result = CliRunner().invoke(list_migrations, ["examples"])
    assert result.exit_code == 0, result.output
    assert "[ ] 0019_baseline\n" in result.output
    assert " ! Migration records for `examples` predate the reset" in result.output
