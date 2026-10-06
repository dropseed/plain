"""
A run's databases are clones of a template an earlier run built. The
template stays on the server for the next run, and goes when the schema it
was built from changes, or when the run building it died before it was
done.

Each test runs an app made for the purpose, in a process of its own, and
reads what the run says about its template in the `--json` document.
"""

import json
import subprocess
import sys
from dataclasses import replace

from plain.postgres.databases import (
    database_exists,
    get_database_comment,
    set_database_comment,
)
from plain.postgres.testing.leftovers import TEMPLATE_BUILDING, read_template_record
from postgres_test_helpers import ScratchApp, make_scratch_app, templates_of

A_TEST = {"tests/test_one.py": "def test_one():\n    pass\n"}

# A package with one migration that does nothing: the migration file is
# part of what the template is built from, so a change to it is a new
# template, and there is no model for convergence to want a table for.
A_MIGRATION = "widgets/migrations/0001_initial.py"
A_PACKAGE_WITH_A_MIGRATION = {
    "app/settings.py": (
        'SECRET_KEY = "test"\n'
        'URLS_ROUTER = "app.urls.AppRouter"\n'
        'INSTALLED_PACKAGES = ["plain.postgres", "widgets"]\n'
    ),
    "widgets/__init__.py": "",
    "widgets/migrations/__init__.py": "",
    A_MIGRATION: (
        "from plain.postgres import migrations\n"
        "\n"
        "\n"
        "class Migration(migrations.Migration):\n"
        "    dependencies = ()\n"
        "    operations = ()\n"
    ),
    **A_TEST,
}


def the_document(output: str) -> dict:
    """The `--json` document in a run's output, which has what the run
    wrote to stderr before it."""
    start = output.index("{")
    return json.loads(output[start:])


def what_was_done_about_the_template(output: str) -> list[str]:
    """What the run said it did under `PostgresTestLifecycle`, in order."""
    phases = {phase["name"]: phase for phase in the_document(output)["phases"]}
    [postgres] = [
        part
        for part in phases["lifecycle_setup"]["parts"]
        if part["name"] == "PostgresTestLifecycle"
    ]
    return [part["name"] for part in postgres["parts"]]


def test_the_first_run_builds_the_template_and_the_next_clones_it():
    app = make_scratch_app(A_TEST)

    exit_code, output = app.run(arguments=("--json",))

    assert exit_code == 0, output
    assert what_was_done_about_the_template(output) == [
        "built template (0 migrations)",
        "cloned template",
    ]
    [template] = templates_of(app)
    assert template.startswith(f"test_{app.configured_name}_t")

    exit_code, output = app.run(arguments=("--json",))

    assert exit_code == 0, output
    assert what_was_done_about_the_template(output) == ["cloned template"]
    assert templates_of(app) == [template]


def test_a_changed_migration_is_a_new_template_and_the_old_one_goes():
    app = make_scratch_app(A_PACKAGE_WITH_A_MIGRATION)
    exit_code, output = app.run(arguments=("--json",))
    assert exit_code == 0, output
    assert what_was_done_about_the_template(output)[0] == "built template (1 migration)"
    [before] = templates_of(app)

    with open(app.root / A_MIGRATION, "a") as migration:
        migration.write("    # a change to the file\n")
    exit_code, output = app.run(arguments=("--json",))

    assert exit_code == 0, output
    assert what_was_done_about_the_template(output) == [
        "built template (1 migration)",
        "cloned template",
    ]
    [after] = templates_of(app)
    assert after != before
    assert not database_exists(app.config, name=before)


def a_process_id_nothing_has() -> int:
    """The id of a process that has just ended."""
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def left_half_built(app: ScratchApp, template: str) -> None:
    """Make the template look like one whose builder died partway: its
    record says it was being built, by a process that is gone."""
    record = read_template_record(get_database_comment(app.config, name=template))
    assert record is not None
    half_built = replace(
        record, state=TEMPLATE_BUILDING, pid=a_process_id_nothing_has()
    )
    set_database_comment(app.config, name=template, comment=half_built.as_comment())


def test_a_template_a_dead_run_left_half_built_is_built_again():
    app = make_scratch_app(A_TEST)
    exit_code, output = app.run(arguments=("--json",))
    assert exit_code == 0, output
    [template] = templates_of(app)
    left_half_built(app, template)

    exit_code, output = app.run(arguments=("--json",))

    assert exit_code == 0, output
    assert what_was_done_about_the_template(output) == [
        "built template (0 migrations)",
        "cloned template",
    ]
    assert templates_of(app) == [template]
    record = read_template_record(get_database_comment(app.config, name=template))
    assert record is not None
    assert record.state == "ready"


def test_an_isolated_test_gets_a_clone_of_the_template_too():
    app = make_scratch_app(
        {
            "tests/test_isolated.py": (
                "from plain.postgres import get_connection\n"
                "from plain.postgres.testing import isolated_db\n"
                "\n"
                "\n"
                "@isolated_db\n"
                "def test_the_migration_records_came_with_the_clone():\n"
                "    with get_connection().cursor() as cursor:\n"
                "        cursor.execute(\n"
                "            \"SELECT to_regclass('plainmigrations') IS NOT NULL\"\n"
                "        )\n"
                "        assert cursor.fetchone()[0]\n"
            ),
        }
    )

    exit_code, output = app.run()

    assert exit_code == 0, output
    assert "1 passed" in output
