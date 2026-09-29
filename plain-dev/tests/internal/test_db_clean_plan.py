"""
What `plain db clean` may drop: the rule, on made-up facts.

Nothing here touches a database or a disk. `plan_clean` is given what is
known about each database and each checkout, and sorts the databases into
what to drop and what to leave.
"""

from dataclasses import replace

from plain.dev.postgres.cleaning import (
    Checkout,
    CleanFacts,
    CleanPlan,
    OwnerPath,
    plan_clean,
)
from plain.testing import cases

MAIN = "/work/plain/example"
WORKTREES = "/work/plain/.claude/worktrees"

GONE = OwnerPath(exists=False, parent_exists=False)
THERE = OwnerPath(exists=True, parent_exists=True)


def a_checkout(path: str, *, database: str | None, exists: bool = True) -> Checkout:
    return Checkout(
        path=path,
        worktree=path.removesuffix("/example"),
        exists=exists,
        database=database if exists else None,
    )


def a_database(
    name: str,
    *,
    made_by: str | None,
    owner_path: OwnerPath | None = GONE,
    connections: int = 0,
) -> CleanFacts:
    return CleanFacts(
        name=name,
        size_bytes=7_000_000,
        recorded_checkout=made_by,
        owner_path=owner_path if made_by else None,
        connections=connections,
        is_test=False,
    )


def a_test_database(name: str, *, run_is_dead: bool, verdict: str) -> CleanFacts:
    return CleanFacts(
        name=name,
        size_bytes=7_000_000,
        recorded_checkout=None,
        owner_path=None,
        connections=0,
        is_test=True,
        run_is_dead=run_is_dead,
        run_verdict=verdict,
    )


def plan_for(
    *databases: CleanFacts,
    checkouts: list[Checkout] | None = None,
    current: str = "example_plain_test_fixes",
    in_git: bool = True,
) -> CleanPlan:
    if checkouts is None:
        checkouts = [
            a_checkout(MAIN, database="example"),
            a_checkout(
                f"{WORKTREES}/plain-test-fixes/example",
                database="example_plain_test_fixes",
            ),
        ]
    return plan_clean(
        list(databases),
        project_main="example",
        current=current,
        checkouts=checkouts,
        in_git=in_git,
    )


def dropped(plan: CleanPlan) -> list[str]:
    return [item.name for item in plan.drop]


def why_left(plan: CleanPlan, name: str) -> str:
    (item,) = [item for item in plan.leave if item.name == name]
    return item.reason


def test_a_database_whose_checkout_is_gone_is_dropped():
    database = a_database(
        "example_typed_writes", made_by=f"{WORKTREES}/typed-writes/example"
    )

    plan = plan_for(database)

    assert dropped(plan) == ["example_typed_writes"]
    assert plan.drop[0].reason == "its checkout is gone"
    assert plan.drop[0].owner == f"{WORKTREES}/typed-writes/example"


def test_every_database_is_in_the_plan_dropped_or_left():
    plan = plan_for(
        a_database("example", made_by=MAIN, owner_path=THERE),
        a_database("example_typed_writes", made_by=f"{WORKTREES}/typed-writes/example"),
        a_database("scratch", made_by=None),
    )

    assert dropped(plan) == ["example_typed_writes"]
    assert [item.name for item in plan.leave] == ["example", "scratch"]


def test_a_database_a_live_checkout_uses_is_left_whoever_its_metadata_names():
    """The worktree was removed and made again somewhere else, or pointed
    at the database with `plain db use`. The metadata still names the
    checkout that made it, which is gone."""
    database = a_database(
        "example_loginlink_link_semantics",
        made_by="/somewhere/it/used/to/be/loginlink-link-semantics/example",
    )
    uses_it = a_checkout(
        f"{WORKTREES}/loginlink-link-semantics/example",
        database="example_loginlink_link_semantics",
    )

    plan = plan_for(database, checkouts=[a_checkout(MAIN, database="example"), uses_it])

    assert dropped(plan) == []
    assert why_left(plan, "example_loginlink_link_semantics") == (
        f"the checkout at {WORKTREES}/loginlink-link-semantics/example"
        " is configured to use it"
    )


def test_the_projects_main_database_is_left_though_its_checkout_is_gone():
    plan = plan_for(a_database("example", made_by="/work/old-place/example"))

    assert dropped(plan) == []
    assert "main database" in why_left(plan, "example")


def test_this_checkouts_database_is_left_though_its_metadata_names_another():
    plan = plan_for(
        a_database("example_shared", made_by="/work/gone/example"),
        current="example_shared",
    )

    assert dropped(plan) == []
    assert why_left(plan, "example_shared") == "this checkout's database"


def test_a_database_with_no_recorded_owner_is_left():
    plan = plan_for(a_database("example_scratch", made_by=None))

    assert dropped(plan) == []
    assert why_left(plan, "example_scratch") == "no record of which checkout made it"


def test_a_database_whose_checkout_is_there_is_left():
    plan = plan_for(
        a_database(
            "example_plain_forms",
            made_by=f"{WORKTREES}/plain-forms/example",
            owner_path=THERE,
        )
    )

    assert dropped(plan) == []
    assert why_left(plan, "example_plain_forms") == "its checkout is there"


def test_a_worktree_git_still_lists_is_not_gone_though_its_directory_is_missing():
    """On a volume that isn't mounted, or removed by hand and not pruned."""
    missing = a_checkout("/Volumes/Work/plain-wt/example", database=None, exists=False)
    database = a_database("example_plain_wt", made_by="/Volumes/Work/plain-wt/example")

    plan = plan_for(database, checkouts=[a_checkout(MAIN, database="example"), missing])

    assert dropped(plan) == []
    reason = why_left(plan, "example_plain_wt")
    assert "git lists a worktree at /Volumes/Work/plain-wt" in reason
    assert "git worktree prune" in reason


def test_a_worktree_with_a_name_that_starts_anothers_doesnt_hold_its_path():
    """`/work/wt/plain-test` is listed and missing. `/work/wt/plain-test-fixes`
    is not in it."""
    missing = a_checkout("/work/wt/plain-test/example", database=None, exists=False)
    database = a_database(
        "example_plain_test_fixes", made_by="/work/wt/plain-test-fixes/example"
    )

    plan = plan_for(
        database,
        checkouts=[a_checkout(MAIN, database="example"), missing],
        current="example",
    )

    assert dropped(plan) == ["example_plain_test_fixes"]


@cases(
    (OwnerPath(exists=False, parent_exists=True), ["example_copy"]),
    (OwnerPath(exists=False, parent_exists=False), []),
)
def test_outside_git_a_missing_path_proves_nothing_when_what_held_it_is_missing_too(
    owner_path, expected
):
    database = a_database(
        "example_copy", made_by="/Volumes/Work/copy", owner_path=owner_path
    )

    plan = plan_for(
        database,
        checkouts=[a_checkout("/work/plain", database="example")],
        current="example",
        in_git=False,
    )

    assert dropped(plan) == expected
    if not expected:
        assert "can't be told" in why_left(plan, "example_copy")


@cases((1, "1 connection is open"), (2, "2 connections are open"))
def test_a_database_something_is_connected_to_is_left(count, said):
    database = a_database(
        "example_typed_writes",
        made_by=f"{WORKTREES}/typed-writes/example",
        connections=count,
    )

    plan = plan_for(database)

    assert dropped(plan) == []
    assert said in why_left(plan, "example_typed_writes")


def test_a_test_database_is_dropped_on_its_runs_verdict_and_nothing_else():
    dead = a_test_database(
        "test_example_plain_test_fixes_r4821",
        run_is_dead=True,
        verdict="a test run left it and is no longer alive",
    )
    live = a_test_database(
        "test_example_plain_test_fixes_r5000",
        run_is_dead=False,
        verdict="a run in progress holds it",
    )
    unrecorded = a_test_database(
        "test_example_something",
        run_is_dead=False,
        verdict="it carries no record that a test run made it",
    )

    plan = plan_for(dead, live, unrecorded)

    assert dropped(plan) == ["test_example_plain_test_fixes_r4821"]
    assert why_left(plan, "test_example_plain_test_fixes_r5000") == (
        "a run in progress holds it"
    )
    assert "no record" in why_left(plan, "test_example_something")
    assert {item.owner for item in (*plan.drop, *plan.leave)} == {"(test database)"}


def test_a_test_database_a_checkout_is_configured_to_use_is_left():
    dead = a_test_database(
        "test_example_r4821", run_is_dead=True, verdict="a test run left it"
    )
    uses_it = a_checkout("/work/odd/example", database="test_example_r4821")

    plan = plan_for(dead, checkouts=[a_checkout(MAIN, database="example"), uses_it])

    assert dropped(plan) == []


def test_the_databases_the_incident_left_standing_are_all_left():
    """The plain project's server as it was afterwards. Nothing on it is
    debris, and the plan says so of each."""
    live = [
        ("example", MAIN),
        ("example_plain_forms", f"{WORKTREES}/plain-forms/example"),
        ("example_plain_html", f"{WORKTREES}/plain-html/example"),
        ("example_plain_test_fixes", f"{WORKTREES}/plain-test-fixes/example"),
        ("example_plain_testing", f"{WORKTREES}/plain-testing/example"),
        ("example_value_type_hook", f"{WORKTREES}/value-type-hook/example"),
    ]
    scratch = [
        "example_plain_test_fixes_r1",
        "example_plain_test_fixes_r2",
        "example_plain_test_fixes_r3",
        "example_plain_testing_pg1",
        "example_plain_testing_pg2",
    ]
    databases = [
        a_database(name, made_by=path, owner_path=THERE) for name, path in live
    ] + [a_database(name, made_by=None) for name in scratch]
    checkouts = [a_checkout(path, database=name) for name, path in live]

    plan = plan_for(*databases, checkouts=checkouts)

    assert dropped(plan) == []
    assert len(plan.leave) == 11


def test_the_facts_are_not_changed_by_planning():
    database = a_database("example_gone", made_by="/work/gone/example")
    before = replace(database)

    plan_for(database)

    assert database == before
