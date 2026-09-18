"""`plain migrations reset` writes the baseline the runtime already reads.

`plan_reset` builds it, `validate_reset` proves the post-reset graph loads
and reproduces the models; the CLI writes and deletes. These tests copy the
real `examples` history into the temporary migrations root so a reset of it
is the reset of an eighteen-migration package with a circular FK inside.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner
from plain.postgres import get_connection
from plain.postgres.cli.migrations import apply, reset
from plain.postgres.migrations import operations
from plain.postgres.migrations.autodetector import detect_model_changes
from plain.postgres.migrations.exceptions import BadMigrationError
from plain.postgres.migrations.loader import MigrationLoader
from plain.postgres.migrations.recorder import MigrationRecorder
from plain.postgres.migrations.reset import plan_reset, validate_reset
from plain.postgres.migrations.writer import MigrationWriter

REAL_EXAMPLES = Path(__file__).parent.parent / "app" / "examples" / "migrations"
LEAF = "0018_storageparametersexample"


def migration_source(
    *,
    dependencies: tuple[tuple[str, str], ...] = (),
    operations: str = "()",
    prelude: str = "",
) -> str:
    return f"""\
from plain import postgres
from plain.postgres import migrations
{prelude}

class Migration(migrations.Migration):
    dependencies = {dependencies!r}
    operations = {operations}
"""


def create_model(name: str, extra_fields: str = "") -> str:
    return (
        f'migrations.CreateModel(name="{name}", fields=['
        f'("id", postgres.PrimaryKeyField()){extra_fields}])'
    )


@pytest.fixture
def migrations_dir(temp_migrations: Callable[..., Path], db: None) -> Path:
    root = temp_migrations("examples", "html")
    for path in REAL_EXAMPLES.glob("0*.py"):
        shutil.copy(path, root / "examples" / path.name)
    return root


def loader() -> MigrationLoader:
    return MigrationLoader(get_connection())


def test_reset_of_the_examples_history(migrations_dir: Path) -> None:
    current = loader()
    plan = plan_reset(current, "examples")

    assert plan.baseline.name == "0019_baseline"
    assert plan.baseline.supersedes == LEAF
    assert plan.baseline.since == ""
    assert plan.baseline.initial is None
    assert plan.baseline.dependencies == []
    assert set(plan.baseline.retired) == {p.stem for p in REAL_EXAMPLES.glob("0*.py")}
    assert sorted(p.name for p in plan.delete) == sorted(
        p.name for p in REAL_EXAMPLES.glob("0*.py")
    )

    created = [
        op.name
        for op in plan.baseline.operations
        if isinstance(op, operations.CreateModel)
    ]
    state = current.project_state()
    assert sorted(name.lower() for name in created) == sorted(
        name for label, name in state.models if label == "examples"
    )
    assert all(
        not (set(op.options) & {"indexes", "constraints", "storage_parameters"})
        for op in plan.baseline.operations
        if isinstance(op, operations.CreateModel)
    )
    # A circular FK comes out as two CreateModels and one AddField after both.
    added = {
        (op.model_name, op.name)
        for op in plan.baseline.operations
        if isinstance(op, operations.AddField)
    }
    assert added & {("circb", "partner"), ("circa", "partner")}

    validate_reset(current, plan)


def test_written_baseline_loads_clean_with_the_history_gone(
    migrations_dir: Path,
) -> None:
    plan = plan_reset(loader(), "examples")
    writer = MigrationWriter(plan.baseline)
    source = writer.as_string()
    assert not writer.needs_manual_porting
    (migrations_dir / "examples" / writer.filename).write_text(source)
    for path in plan.delete:
        path.unlink()

    after = loader()
    assert after.baselines["examples"].name == "0019_baseline"
    assert detect_model_changes(after, {"examples"}) == {}


def test_dependencies_come_from_what_the_baseline_references(
    migrations_dir: Path,
) -> None:
    """The history pinned `examples` where Feature was created and, later,
    the leaf for no reason. The baseline's FK now points at Tag - Feature
    renamed in 0014 - so it depends on 0014: enough for a fresh database,
    and not the dead pin."""
    (migrations_dir / "html" / "0001_initial.py").write_text(
        migration_source(
            dependencies=(("examples", "0005_feature_carfeature_car_features"),),
            operations="("
            + create_model(
                "Note",
                ', ("feature", postgres.ForeignKeyField(to="examples.feature", on_delete=postgres.CASCADE))',
            )
            + ",)",
        )
    )
    (migrations_dir / "html" / "0002_noop.py").write_text(
        migration_source(
            dependencies=(("html", "0001_initial"), ("examples", LEAF)),
        )
    )
    # The rename came after Note existed: replay 0014 after html.0001.
    rename = next((migrations_dir / "examples").glob("0014_*.py"))
    rename.write_text(
        rename.read_text().replace(
            "    dependencies = (",
            '    dependencies = (\n        ("html", "0001_initial"),',
            1,
        )
    )

    plan = plan_reset(loader(), "html")

    assert plan.baseline.dependencies == [
        ("examples", "0014_widget_rename_feature_tag_remove_carfeature_car_and_more")
    ]
    (create,) = plan.baseline.operations
    assert isinstance(create, operations.CreateModel)
    assert (
        dict(create.fields)["feature"].remote_field.model_ref.lower() == "examples.tag"
    )


NOOP = "\n\ndef noop(models, schema_editor):\n    pass\n"


@pytest.mark.parametrize(
    ("operations_source", "refused"),
    [
        (
            f"({create_model('Note')}, migrations.RunPython(noop),)",
            "html.0001_initial: Raw Python operation (operation 1)",
        ),
        (
            f"({create_model('Note')}, migrations.SeparateDatabaseAndState(database_operations=[migrations.RunSQL('select 1')]),)",
            "Raw SQL operation",
        ),
        # A table created on the database side only never reaches state.
        (
            f"({create_model('Note')}, migrations.SeparateDatabaseAndState(database_operations=[{create_model('Shadow')}]),)",
            "Create model Shadow (operation 1)",
        ),
    ],
)
def test_unregenerable_operations_refuse(
    migrations_dir: Path, operations_source: str, refused: str
) -> None:
    (migrations_dir / "html" / "0001_initial.py").write_text(
        migration_source(operations=operations_source, prelude=NOOP)
    )

    with pytest.raises(BadMigrationError) as excinfo:
        plan_reset(loader(), "html")

    assert refused in str(excinfo.value)
    assert "skip_on_reset=True" in str(excinfo.value)


def test_skipped_operations_are_left_out(migrations_dir: Path) -> None:
    (migrations_dir / "html" / "0001_initial.py").write_text(
        migration_source(
            operations=f"({create_model('Note')}, migrations.RunPython(noop, skip_on_reset=True), migrations.RunSQL('select 1', skip_on_reset=True),)",
            prelude=NOOP,
        )
    )

    plan = plan_reset(loader(), "html")

    assert [type(op) for op in plan.baseline.operations] == [operations.CreateModel]


def test_second_reset_folds_the_previous_baseline_into_retired(
    migrations_dir: Path,
) -> None:
    (migrations_dir / "html" / "0002_baseline.py").write_text(
        migration_source(operations=f"({create_model('Note')},)").replace(
            "    dependencies",
            '    supersedes = "0001_initial"\n    retired = ()\n    since = "1.0"\n    dependencies',
        )
    )
    (migrations_dir / "html" / "0003_more.py").write_text(
        migration_source(
            dependencies=(("html", "0002_baseline"),),
            operations=f"({create_model('Other')},)",
        )
    )

    plan = plan_reset(loader(), "html")

    assert plan.baseline.name == "0004_baseline"
    assert plan.baseline.supersedes == "0003_more"
    assert plan.baseline.retired == ("0001_initial", "0002_baseline", "0003_more")


def test_second_reset_refuses_while_the_first_is_unreleased(
    migrations_dir: Path,
) -> None:
    (migrations_dir / "html" / "0002_baseline.py").write_text(
        migration_source(operations=f"({create_model('Note')},)").replace(
            "    dependencies",
            '    supersedes = "0001_initial"\n    retired = ()\n    since = ""\n    dependencies',
        )
    )
    (migrations_dir / "html" / "0003_more.py").write_text(
        migration_source(dependencies=(("html", "0002_baseline"),))
    )

    with pytest.raises(BadMigrationError, match="no release has shipped"):
        plan_reset(loader(), "html")


def test_first_reset_cycle_is_refused_before_anything_changes(
    migrations_dir: Path,
) -> None:
    """`examples` pinned an early `html` migration; the model the
    baseline needs is created after that pin. The only root the graph can
    give the baseline closes a cycle, and validation says so."""
    (migrations_dir / "html" / "0001_initial.py").write_text(
        migration_source(operations=f"({create_model('Note')},)")
    )
    (migrations_dir / "examples" / "0019_gadget.py").write_text(
        migration_source(
            dependencies=(("examples", LEAF), ("html", "0001_initial")),
            operations=f"({create_model('Gadget')},)",
        )
    )
    (migrations_dir / "html" / "0002_note_gadget.py").write_text(
        migration_source(
            dependencies=(
                ("html", "0001_initial"),
                ("examples", "0019_gadget"),
            ),
            operations='(migrations.AddField(model_name="note", name="gadget", field=postgres.ForeignKeyField(to="examples.gadget", on_delete=postgres.CASCADE, allow_null=True)),)',
        )
    )
    before = sorted(p.name for p in (migrations_dir / "html").glob("0*.py"))

    current = loader()
    plan = plan_reset(current, "html")
    assert plan.baseline.dependencies == [("examples", "0019_gadget")]
    with pytest.raises(BadMigrationError) as excinfo:
        validate_reset(current, plan)
    # The cycle, reported from whichever node the search entered it.
    assert "examples.0019_gadget" in str(excinfo.value)
    assert "html.0003_baseline" in str(excinfo.value)

    assert sorted(p.name for p in (migrations_dir / "html").glob("0*.py")) == before
    # The caller's loader still holds its own, un-rewritten graph.
    assert ("html", "0002_note_gadget") in current.graph.nodes


def test_nothing_to_reset(migrations_dir: Path) -> None:
    with pytest.raises(BadMigrationError, match="no migrations to reset"):
        plan_reset(loader(), "html")


def test_two_leaves_refuse(migrations_dir: Path) -> None:
    (migrations_dir / "examples" / "0019_a.py").write_text(
        migration_source(dependencies=(("examples", LEAF),))
    )
    (migrations_dir / "examples" / "0019_b.py").write_text(
        migration_source(dependencies=(("examples", LEAF),))
    )
    with pytest.raises(BadMigrationError, match="2 leaf migrations"):
        plan_reset(loader(), "examples")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture
def repo(migrations_dir: Path) -> Path:
    """The temporary migrations root, committed in a git repository."""
    root = migrations_dir.parent
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "history")
    return root


def examples_files(migrations_dir: Path) -> list[str]:
    return sorted(p.name for p in (migrations_dir / "examples").glob("0*.py"))


def test_reset_command_writes_and_deletes_then_the_runtime_adopts(
    repo: Path, migrations_dir: Path
) -> None:
    result = CliRunner().invoke(reset, ["examples", "--since", "2.0"])

    assert result.exit_code == 0, result.output
    assert "Supersedes 0018_storageparametersexample" in result.output
    assert "Recover from any failure with: git checkout --" in result.output
    assert "&& rm " in result.output
    assert "Commit the new file and the deletions together" in result.output
    assert "`since` is empty" not in result.output
    assert "must have applied `examples.0018_storageparametersexample`" in result.output
    assert examples_files(migrations_dir) == ["0019_baseline.py"]
    source = (migrations_dir / "examples" / "0019_baseline.py").read_text()
    assert "supersedes = '0018_storageparametersexample'" in source
    assert "since = '2.0'" in source
    assert "initial = True" not in source

    # The test database recorded the sentinel: the runtime adopts.
    applied = CliRunner().invoke(apply, ["--no-input"])
    assert applied.exit_code == 0, applied.output
    assert "examples.0019_baseline (baseline: recorded, not run)" in applied.output


def test_generated_baseline_runs_on_a_cleared_database(
    repo: Path, migrations_dir: Path
) -> None:
    """Adoption never executes the generated DDL; a cleared database does."""
    result = CliRunner().invoke(reset, ["examples"])
    assert result.exit_code == 0, result.output

    connection = get_connection()
    with connection.cursor() as cursor:
        for table in connection.table_names(cursor):
            if table.startswith("examples_"):
                cursor.execute(f'DROP TABLE "{table}" CASCADE')
    recorder = MigrationRecorder(connection)
    for label, name in list(recorder.applied_migrations()):
        if label == "examples":
            recorder.record_unapplied(label, name)

    applied = CliRunner().invoke(apply, ["--no-input"])
    assert applied.exit_code == 0, applied.output
    assert "recorded, not run" not in applied.output
    tables = connection.table_names()
    assert "examples_circa" in tables
    assert "examples_widgettag" in tables
    assert detect_model_changes(loader(), {"examples"}) == {}


def test_dry_run_changes_nothing(repo: Path, migrations_dir: Path) -> None:
    before = examples_files(migrations_dir)

    result = CliRunner().invoke(reset, ["examples", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "class Migration(migrations.Migration):" in result.output
    assert "Dry run - nothing written or deleted." in result.output
    assert "Recover from any failure" not in result.output
    assert examples_files(migrations_dir) == before


def test_uncommitted_history_refuses(repo: Path, migrations_dir: Path) -> None:
    leaf = migrations_dir / "examples" / f"{LEAF}.py"
    leaf.write_text(leaf.read_text() + "\n# edited\n")
    result = CliRunner().invoke(reset, ["examples"])
    assert result.exit_code != 0
    assert "has uncommitted changes" in result.output
    assert f"{LEAF}.py" in result.output

    git(repo, "checkout", "--", ".")
    (migrations_dir / "examples" / "0019_new.py").write_text(
        migration_source(dependencies=(("examples", LEAF),))
    )
    result = CliRunner().invoke(reset, ["examples"])
    assert result.exit_code != 0
    assert "Not tracked by git" in result.output
    assert "0019_new.py" in result.output
    assert examples_files(migrations_dir)[-1] == "0019_new.py"


def test_outside_a_repository_refuses(migrations_dir: Path) -> None:
    result = CliRunner().invoke(reset, ["examples"])
    assert result.exit_code != 0
    assert "git could not read" in result.output
    assert "not a git repository" in result.output
    assert len(examples_files(migrations_dir)) == 18


def test_pending_model_changes_refuse(migrations_dir: Path) -> None:
    (migrations_dir / "examples" / f"{LEAF}.py").unlink()
    root = migrations_dir.parent
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "history without the leaf")

    result = CliRunner().invoke(reset, ["examples"])

    assert result.exit_code != 0
    assert "model changes its migrations don't hold" in result.output
    assert "Create model StorageParametersExample" in result.output
    assert len(examples_files(migrations_dir)) == 17


def test_code_defined_in_a_deleted_migration_is_flagged(migrations_dir: Path) -> None:
    (migrations_dir / "html" / "0001_initial.py").write_text(
        migration_source(
            operations=f"({create_model('Note', ', ("label", LabelField(max_length=10))')},)",
            prelude="\n\nclass LabelField(postgres.TextField):\n    pass\n",
        )
    )
    plan = plan_reset(loader(), "html")
    writer = MigrationWriter(plan.baseline)
    writer.as_string()
    assert writer.needs_manual_porting
