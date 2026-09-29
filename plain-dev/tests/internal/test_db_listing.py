"""
Which databases on a server are a project's, and which of those are test
databases. The server here is a list made up for the test.
"""

import json
from collections.abc import Generator
from contextlib import contextmanager

from plain.dev.postgres.backends import Server
from plain.dev.postgres.cluster import Cluster, DevDatabase
from plain.postgres import databases as postgres_databases
from plain.postgres.databases import DatabaseInfo
from plain.postgres.test.leftovers import TEMPLATE_READY, RunRecord, TemplateRecord
from plain.testing import patch


def made_by_a_checkout(path: str) -> str:
    return json.dumps({"checkout": path, "branch": "main", "created_via": "template"})


def the_template_of(database: str) -> str:
    return TemplateRecord(
        database=database,
        schema="a" * 64,
        state=TEMPLATE_READY,
        directory="/work/plain/example",
        host="this-machine",
        pid=4821,
    ).as_comment()


def made_by_a_run_of(database: str) -> str:
    return RunRecord(
        database=database,
        run=f"test_{database}_r4821",
        token="0123456789abcdef",
        directory="/work/plain/example",
        host="this-machine",
        pid=4821,
    ).as_comment()


@contextmanager
def a_server_with(databases: dict[str, str | None]) -> Generator[Cluster]:
    infos = [
        DatabaseInfo(name=name, comment=comment, size_bytes=1)
        for name, comment in databases.items()
    ]
    with patch(postgres_databases, "list_databases", lambda config: infos):
        yield Cluster(
            Server(
                backend="docker",
                host="127.0.0.1",
                port=5432,
                user="postgres",
                password="postgres",
                container="made-up",
            )
        )


def listed(databases: dict[str, str | None]) -> dict[str, DevDatabase]:
    with a_server_with(databases) as cluster:
        return {
            database.name: database for database in cluster.list_databases("example")
        }


def test_a_database_is_the_projects_by_its_metadata_or_its_name():
    found = listed(
        {
            "example": made_by_a_checkout("/work/plain/example"),
            "example_plain_forms": None,
            "scratch": made_by_a_checkout("/work/plain/example"),
            "another_project": None,
            "examples": None,
        }
    )

    assert set(found) == {"example", "example_plain_forms", "scratch"}
    assert not any(database.is_test for database in found.values())


def test_a_test_database_is_the_projects_by_the_database_its_record_names():
    found = listed(
        {
            "example": None,
            "example_plain_test": None,
            "zz_named_anything": made_by_a_run_of("example_plain_test"),
            "test_another_r1": made_by_a_run_of("another_project"),
        }
    )

    assert set(found) == {"example", "example_plain_test", "zz_named_anything"}
    assert found["zz_named_anything"].is_test
    assert found["zz_named_anything"].run_record is not None
    assert found["zz_named_anything"].run_record.database == "example_plain_test"


def test_a_template_is_the_projects_by_the_database_its_record_names():
    found = listed(
        {
            "example": None,
            "test_example_taaaaaaaa": the_template_of("example"),
            "zz_named_anything": the_template_of("example_plain_test"),
            "test_another_tbbbbbbbb": the_template_of("another_project"),
        }
    )

    assert set(found) == {"example", "test_example_taaaaaaaa", "zz_named_anything"}
    for name in ("test_example_taaaaaaaa", "zz_named_anything"):
        assert found[name].is_test
        assert found[name].run_record is None
    template = found["zz_named_anything"].template_record
    assert template is not None
    assert template.database == "example_plain_test"


def test_a_test_database_of_a_database_that_is_gone_is_still_the_projects():
    """The checkout's database was dropped. What its runs left is there."""
    found = listed({"test_whatever": made_by_a_run_of("example_gone")})

    assert set(found) == {"test_whatever"}


def test_a_database_only_named_like_a_test_database_is_listed_without_a_record():
    found = listed(
        {
            "test_example": None,
            "test_example_plain_test_r4821": None,
            "test_something_else": None,
            "test_examples": None,
        }
    )

    assert set(found) == {"test_example", "test_example_plain_test_r4821"}
    assert all(database.is_test for database in found.values())
    assert all(database.run_record is None for database in found.values())


def test_a_development_database_is_not_a_test_database_for_being_named_test():
    """`plain db create test_example_data` made it, and says so."""
    found = listed(
        {"test_example_data": made_by_a_checkout("/work/plain/example")},
    )

    assert set(found) == {"test_example_data"}
    assert not found["test_example_data"].is_test
    assert found["test_example_data"].checkout == "/work/plain/example"
