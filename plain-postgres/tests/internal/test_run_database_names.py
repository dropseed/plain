"""How a run's databases are named. A name is only ever written: what a
database is, and whose, is read from the record in it."""

from plain.postgres.dialect import MAX_NAME_LENGTH
from plain.postgres.testing.database import (
    isolated_database_name,
    legacy_database_name,
    shared_database_name,
)


def test_the_shared_database_is_named_for_the_checkout_and_the_run():
    assert (
        shared_database_name("shop_main", run_token="r4821") == "test_shop_main_r4821"
    )


def test_an_isolated_database_adds_the_tests_name():
    name = isolated_database_name(
        "test_shop_main_r4821", test_name="test_adds_an_index[btree]"
    )

    assert name == "test_shop_main_r4821_adds_an_index_btree_"


def test_a_long_test_name_is_cut_to_fit():
    shared = shared_database_name("shop_main", run_token="r4821")

    name = isolated_database_name(shared, test_name="test_" + "very_long_" * 12)

    assert len(name) == MAX_NAME_LENGTH
    assert name.startswith(f"{shared}_very_long_")


def test_a_long_database_name_is_cut_the_same_way_for_every_run():
    database = "a_project_with_a_long_name_and_a_checkout_with_one_too"

    short_token = shared_database_name(database, run_token="r7")
    long_token = shared_database_name(database, run_token="r4194304x0000")

    start = legacy_database_name(database)
    assert short_token == f"{start}_r7"
    assert long_token == f"{start}_r4194304x0000"
    assert len(long_token) <= MAX_NAME_LENGTH
    # Room is left for an isolated test's name after the longest of them.
    assert (
        len(isolated_database_name(long_token, test_name="test_x")) <= MAX_NAME_LENGTH
    )
