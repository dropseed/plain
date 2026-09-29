"""
What a test run may drop that it didn't make: the rule, on made-up facts.

Nothing here touches a database. `judge_leftover` is given what is known
about one and says whether it is a dead run's, and these are the cases it
has to get right, the ones that went wrong among them.
"""

import json
from dataclasses import replace

from plain.postgres.test.leftovers import (
    LOCK_SCHEME,
    RECORD_KEY,
    LeftoverFacts,
    RunRecord,
    judge_leftover,
    read_run_record,
    run_lock_key,
)
from plain.test import case, cases


def a_record(*, database: str = "example_plain_test", run: str = "") -> RunRecord:
    return RunRecord(
        database=database,
        run=run or f"test_{database}_r4821",
        token="0123456789abcdef",
        directory="/work/plain-test/example",
        host="this-machine",
        pid=4821,
    )


def what_a_dead_run_left(
    *, name: str = "test_example_plain_test_r4821", record: RunRecord | None = None
) -> LeftoverFacts:
    """Every fact the way it is for a database whose run was killed."""
    return LeftoverFacts(
        name=name,
        record=record or a_record(),
        lock_is_free=True,
        connections=0,
        process_is_running=False,
    )


def test_what_a_dead_run_left_is_dropped():
    verdict = judge_leftover(
        what_a_dead_run_left(), tested_database="example_plain_test"
    )

    assert verdict.drop
    assert "process 4821" in verdict.reason
    assert "/work/plain-test/example" in verdict.reason


def test_a_database_with_no_record_is_left_whatever_it_is_named():
    """`test_something`, which nothing made through this mechanism."""
    facts = LeftoverFacts(
        name="test_example_plain_test",
        record=None,
        lock_is_free=True,
        connections=0,
        process_is_running=None,
    )

    verdict = judge_leftover(facts, tested_database="example_plain_test")

    assert not verdict.drop
    assert not verdict.in_doubt
    assert "no record" in verdict.reason


# The checkouts whose names start each other's. A run of any of them, asked
# about a database of any other, leaves it: a name's start decides nothing.
NESTED = (
    "example",
    "example_plain_test",
    "example_plain_test_fixes",
    "example_plain_testing",
)


@cases(
    *(
        case(asking, made_for, id=f"{asking} asked about {made_for}")
        for asking in NESTED
        for made_for in NESTED
        if asking != made_for
    )
)
def test_another_checkouts_test_database_is_left(asking, made_for):
    record = a_record(database=made_for)
    facts = what_a_dead_run_left(name=record.run, record=record)

    verdict = judge_leftover(facts, tested_database=asking)

    assert not verdict.drop
    assert not verdict.in_doubt
    assert made_for in verdict.reason


@cases(*NESTED)
def test_a_checkouts_own_dead_run_is_dropped(database):
    record = a_record(database=database)
    facts = what_a_dead_run_left(name=record.run, record=record)

    assert judge_leftover(facts, tested_database=database).drop


def test_a_database_a_live_run_holds_is_left():
    facts = replace(what_a_dead_run_left(), lock_is_free=False)

    verdict = judge_leftover(facts, tested_database="example_plain_test")

    assert not verdict.drop
    assert not verdict.in_doubt
    assert verdict.reason == "a run in progress holds it"


def test_a_run_on_code_that_holds_no_lock_is_not_taken_for_dead():
    """Its database carries no record, since the code that writes the record
    is the code that takes the lock."""
    facts = LeftoverFacts(
        name="test_example_plain_test",
        record=None,
        lock_is_free=True,
        connections=1,
        process_is_running=None,
    )

    assert not judge_leftover(facts, tested_database="example_plain_test").drop


def test_a_record_from_code_that_marks_a_run_alive_another_way_proves_nothing():
    record = replace(a_record(), lock="something-newer-2")
    facts = what_a_dead_run_left(record=record)

    verdict = judge_leftover(facts, tested_database="example_plain_test")

    assert not verdict.drop
    assert verdict.in_doubt
    assert "something-newer-2" in verdict.reason


def test_a_free_lock_is_not_enough_when_the_process_is_running():
    """A run whose connection to the maintenance database was lost."""
    facts = replace(what_a_dead_run_left(), process_is_running=True)

    verdict = judge_leftover(facts, tested_database="example_plain_test")

    assert not verdict.drop
    assert verdict.in_doubt
    assert "process 4821" in verdict.reason


@cases((1, "1 connection is open"), (3, "3 connections are open"))
def test_a_free_lock_is_not_enough_when_something_is_connected(count, said):
    facts = replace(what_a_dead_run_left(), connections=count)

    verdict = judge_leftover(facts, tested_database="example_plain_test")

    assert not verdict.drop
    assert verdict.in_doubt
    assert said in verdict.reason


def test_a_run_on_another_machine_is_judged_by_the_lock_and_the_connections():
    facts = replace(what_a_dead_run_left(), process_is_running=None)

    assert judge_leftover(facts, tested_database="example_plain_test").drop


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


def test_a_record_is_read_back_as_it_was_written():
    record = a_record()

    assert read_run_record(record.as_comment()) == record


def a_comment_with(**changes: object) -> str:
    fields = json.loads(a_record().as_comment())[RECORD_KEY]
    fields.update(changes)
    return json.dumps({RECORD_KEY: fields})


@cases(
    case(None, id="no comment"),
    case("", id="an empty comment"),
    case("forked from main", id="not JSON"),
    case("[1, 2]", id="JSON that isn't an object"),
    case(
        '{"checkout": "/work/plain", "created_via": "template"}',
        id="a development database's metadata",
    ),
    case(json.dumps({RECORD_KEY: "yes"}), id="a record that isn't an object"),
    case(json.dumps({RECORD_KEY: {"database": "example"}}), id="fields missing"),
    case(a_comment_with(pid="4821"), id="a process id that isn't a number"),
    case(a_comment_with(pid=True), id="a process id that is a boolean"),
    case(a_comment_with(database=""), id="no database named"),
    case(a_comment_with(run=None), id="no run named"),
    case(a_comment_with(more="than it should hold"), id="a field too many"),
)
def test_what_is_not_a_whole_record_is_no_record(comment):
    assert read_run_record(comment) is None


def test_the_lock_is_keyed_by_the_whole_name_of_the_run():
    keys = {
        run_lock_key(name)
        for name in (
            "test_example_r4821",
            "test_example_plain_test_r4821",
            "test_example_plain_test_fixes_r4821",
            "test_example_plain_test_r48210",
        )
    }

    assert len(keys) == 4


def test_the_scheme_a_record_carries_is_this_codes():
    assert a_record().lock == LOCK_SCHEME
