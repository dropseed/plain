"""QuerySet.upsert() inserts a row or updates the conflicting one.

One INSERT ... ON CONFLICT (unique_fields) DO UPDATE ... RETURNING statement.
Returns (obj, created): obj is hydrated from the post-write row -- no second
query -- and created is True on insert, False on conflict-update.
"""

from __future__ import annotations

import concurrent.futures
import threading
from datetime import UTC

import psycopg
import pytest
from app.examples.models.relationships import Tag, Widget
from app.examples.models.upsert import (
    UpsertItem,
    UpsertOwner,
    UpsertScope,
    UpsertScopedItem,
)
from plain.postgres import Excluded
from plain.postgres.db import get_connection
from plain.postgres.exceptions import FieldError
from plain.postgres.expressions import F
from plain.postgres.sources import build_connection_params


def test_upsert_inserts_new_row(db):
    obj, created = UpsertItem.query.upsert(
        key="a", value=1, unique_fields=[UpsertItem.key]
    )

    assert created is True
    assert obj.id is not None
    assert obj.key == "a"
    assert obj.value == 1
    assert UpsertItem.query.get(key="a").value == 1


def test_upsert_updates_conflicting_row(db):
    UpsertItem(key="a", value=1).create()
    existing_id = UpsertItem.query.get(key="a").id

    obj, created = UpsertItem.query.upsert(
        key="a", value=99, unique_fields=[UpsertItem.key]
    )

    assert created is False
    # The updated row keeps its primary key, and obj carries the merged value.
    assert obj.id == existing_id
    assert obj.value == 99
    assert UpsertItem.query.count() == 1
    assert UpsertItem.query.get(key="a").value == 99


def test_upsert_defaults_apply_on_insert_and_update(db):
    obj, created = UpsertItem.query.upsert(
        key="a", defaults={"value": 5}, unique_fields=[UpsertItem.key]
    )
    assert (created, obj.value) == (True, 5)

    obj, created = UpsertItem.query.upsert(
        key="a", defaults={"value": 7}, unique_fields=[UpsertItem.key]
    )
    assert (created, obj.value) == (False, 7)


def test_upsert_does_not_call_a_shadowed_callable(db):
    """A callable in a lower-precedence source is never the value, so it must
    never run -- resolving it would fire a side effect nobody asked for.
    """
    calls = []

    def shadowed():
        calls.append("ran")
        return 999

    def also_shadowed():
        calls.append("ran")
        return 998

    obj, _ = UpsertItem.query.upsert(
        key="a",
        value=1,
        defaults={"value": shadowed},
        create_defaults={"value": also_shadowed},
        unique_fields=[UpsertItem.key],
    )

    assert calls == []
    assert obj.value == 1


def test_upsert_create_defaults_apply_on_insert_only(db):
    obj, created = UpsertItem.query.upsert(
        key="a",
        defaults={"value": 1},
        create_defaults={"label": "created"},
        unique_fields=[UpsertItem.key],
    )
    assert (created, obj.label) == (True, "created")

    # On conflict, create_defaults is not applied, so the label is untouched
    # while defaults still updates value.
    obj, created = UpsertItem.query.upsert(
        key="a",
        defaults={"value": 2},
        create_defaults={"label": "ignored-on-conflict"},
        unique_fields=[UpsertItem.key],
    )
    assert created is False
    assert obj.label == "created"
    assert obj.value == 2


def test_upsert_conflict_defaults_increment_counter_atomically(db):
    UpsertItem(key="a", value=10).create()

    obj, created = UpsertItem.query.upsert(
        key="a",
        value=0,  # the value the INSERT would have proposed (ignored on conflict)
        conflict_defaults={"value": F("value") + 1},
        unique_fields=[UpsertItem.key],
    )

    assert created is False
    assert obj.value == 11
    assert UpsertItem.query.get(key="a").value == 11


def test_upsert_conflict_defaults_bind_to_their_own_columns(db):
    """The SET clause is emitted in model field order while conflict_defaults
    is a dict in the caller's order, so the assignments and their parameters
    have to be built in one pass -- otherwise each value binds to the wrong
    column. Declared value-then-label against a model that has label first.
    """
    UpsertItem(key="a", value=1, label="old").create()

    obj, created = UpsertItem.query.upsert(
        key="a",
        value=1,
        label="old",
        conflict_defaults={"value": 42, "label": "HELLO"},
        unique_fields=[UpsertItem.key],
    )

    assert created is False
    assert (obj.value, obj.label) == (42, "HELLO")
    stored = UpsertItem.query.get(key="a")
    assert (stored.value, stored.label) == (42, "HELLO")


def test_upsert_conflict_defaults_set_order_matches_param_order(db, capture_queries):
    UpsertItem(key="a", value=1, label="old").create()

    with capture_queries() as queries:
        UpsertItem.query.upsert(
            key="a",
            value=1,
            label="old",
            conflict_defaults={"value": 42, "label": "HELLO"},
            unique_fields=[UpsertItem.key],
        )

    set_clause = queries[0]["sql"].split("DO UPDATE SET ")[1].split(" RETURNING")[0]
    # label precedes value in the model, so the literals must appear that way
    # round too -- the parameters are interpolated in the order they were sent.
    assert set_clause.index("'HELLO'") < set_clause.index("42")


def test_upsert_conflict_defaults_resolve_callables(db):
    """A callable in conflict_defaults is called, like every other value
    source -- otherwise the callable itself reaches the column and a text
    column stores its repr.
    """
    UpsertItem(key="a", value=1, label="old").create()

    obj, created = UpsertItem.query.upsert(
        key="a",
        value=1,
        label="old",
        conflict_defaults={"label": lambda: "computed", "value": lambda: 42},
        unique_fields=[UpsertItem.key],
    )

    assert created is False
    assert (obj.label, obj.value) == ("computed", 42)
    stored = UpsertItem.query.get(key="a")
    assert (stored.label, stored.value) == ("computed", 42)


def test_upsert_conflict_defaults_do_not_call_expressions(db):
    """An expression is an object, not a callable, so callable resolution has
    to leave it alone for the atomic-counter case to survive.
    """
    UpsertItem(key="a", value=10).create()

    obj, created = UpsertItem.query.upsert(
        key="a",
        value=5,
        conflict_defaults={"value": F("value") + Excluded("value")},
        unique_fields=[UpsertItem.key],
    )

    assert created is False
    assert obj.value == 15


def test_upsert_rejects_a_property_name(db):
    """upsert() derives its SET clause from columns, so a settable property
    would be written on insert and silently dropped on conflict.
    """
    with pytest.raises(FieldError, match="is a property"):
        UpsertItem.query.upsert(
            key="a", label_upper="HELLO", unique_fields=[UpsertItem.key]
        )


def test_upsert_rejects_a_property_name_in_defaults(db):
    with pytest.raises(FieldError, match="is a property"):
        UpsertItem.query.upsert(
            key="a",
            defaults={"label_upper": "HELLO"},
            unique_fields=[UpsertItem.key],
        )


def test_upsert_ignores_queryset_filters(db):
    """upsert() targets the conflict constraint, never the queryset's filters
    -- the related-manager wrappers rely on calling through a filtered
    queryset, so this is documented rather than guarded.
    """
    UpsertItem(key="a", value=1).create()

    obj, created = UpsertItem.query.filter(value=99999).upsert(
        key="a", value=7, unique_fields=[UpsertItem.key]
    )

    assert created is False
    assert obj.value == 7
    assert UpsertItem.query.count() == 1


def test_upsert_conflict_defaults_rejects_the_primary_key(db):
    with pytest.raises(ValueError, match="cannot update primary key fields"):
        UpsertItem.query.upsert(
            key="a",
            conflict_defaults={"id": 999},
            unique_fields=[UpsertItem.key],
        )


def test_upsert_conflict_defaults_rejects_a_database_owned_column(db):
    with pytest.raises(ValueError, match="the database generates its value"):
        UpsertItem.query.upsert(
            key="a",
            conflict_defaults={"created_at": Excluded("created_at")},
            unique_fields=[UpsertItem.key],
        )


def test_upsert_conflict_defaults_apply_on_insert_uses_inserted_value(db):
    # On insert there's no existing row, so the inserted value stands; the
    # conflict_defaults override only takes effect on a later conflict.
    obj, created = UpsertItem.query.upsert(
        key="a",
        value=3,
        conflict_defaults={"value": F("value") + 100},
        unique_fields=[UpsertItem.key],
    )
    assert (created, obj.value) == (True, 3)


def test_upsert_excluded_accumulates_the_proposed_value(db):
    """F() reads the stored row, Excluded() reads the row the INSERT proposed,
    so combining them adds the incoming delta instead of overwriting.
    """
    UpsertItem(key="a", value=10).create()

    obj, created = UpsertItem.query.upsert(
        key="a",
        value=7,
        conflict_defaults={"value": F("value") + Excluded("value")},
        unique_fields=[UpsertItem.key],
    )

    assert created is False
    assert obj.value == 17
    assert UpsertItem.query.get(key="a").value == 17


def test_upsert_excluded_compiles_to_the_excluded_column(db, capture_queries):
    UpsertItem(key="a", value=1).create()

    with capture_queries() as queries:
        UpsertItem.query.upsert(
            key="a",
            value=5,
            conflict_defaults={"value": F("value") + Excluded("value")},
            unique_fields=[UpsertItem.key],
        )

    assert len(queries) == 1
    sql = queries[0]["sql"]
    assert '"value" = ("examples_upsertitem"."value" + EXCLUDED."value")' in sql


def test_upsert_excluded_accumulates_across_repeated_calls(db):
    """Each call adds its own delta to whatever is stored -- the property a
    concurrent caller relies on, exercised serially here.
    """
    for delta in (3, 4, 5):
        obj, _ = UpsertItem.query.upsert(
            key="a",
            value=delta,
            conflict_defaults={"value": F("value") + Excluded("value")},
            unique_fields=[UpsertItem.key],
        )

    # 3 inserted, then +4, then +5.
    assert obj.value == 12
    assert UpsertItem.query.get(key="a").value == 12


def test_excluded_outside_a_conflict_update_is_rejected(db):
    with pytest.raises(FieldError, match="only valid in upsert"):
        UpsertItem.query.filter(key="a").update(value=Excluded("value"))

    with pytest.raises(FieldError, match="only valid in upsert"):
        list(UpsertItem.query.filter(value=Excluded("value")))


@pytest.mark.parametrize(
    "expression",
    [Excluded("value"), F("value") + Excluded("value")],
    ids=["bare", "nested"],
)
@pytest.mark.parametrize(
    "upsert_with",
    [
        lambda expression: UpsertItem.query.upsert(
            key="a", value=expression, unique_fields=[UpsertItem.key]
        ),
        lambda expression: UpsertItem.query.upsert(
            key="a", defaults={"value": expression}, unique_fields=[UpsertItem.key]
        ),
        lambda expression: UpsertItem.query.upsert(
            key="a",
            create_defaults={"value": expression},
            unique_fields=[UpsertItem.key],
        ),
    ],
    ids=["kwargs", "defaults", "create_defaults"],
)
def test_excluded_as_an_inserted_value_is_rejected(
    db, capture_queries, upsert_with, expression
):
    """Excluded() names the row being proposed, so it can't be one of that
    row's own values -- in any of the three value sources, bare or nested, and
    before any SQL is emitted.
    """
    with (
        capture_queries() as queries,
        pytest.raises(FieldError, match="cannot be an inserted value"),
    ):
        upsert_with(expression)

    assert queries == []


def test_excluded_as_an_inserted_value_on_a_text_column_is_rejected(db):
    """A text column would coerce the expression to its repr and write that
    into the row, so the check can't rely on field coercion to catch it.
    """
    with pytest.raises(FieldError, match="cannot be an inserted value"):
        UpsertItem.query.upsert(
            key="a", label=Excluded("label"), unique_fields=[UpsertItem.key]
        )


def test_upsert_excluded_unknown_column_is_rejected(db):
    with pytest.raises(FieldError, match="does not name a column"):
        UpsertItem.query.upsert(
            key="a",
            value=1,
            conflict_defaults={"value": Excluded("typo_field")},
            unique_fields=[UpsertItem.key],
        )


def test_upsert_rejects_updating_a_database_owned_column(db):
    from datetime import datetime

    with pytest.raises(ValueError, match="the database generates its value"):
        UpsertItem.query.upsert(
            key="a",
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
            unique_fields=[UpsertItem.key],
        )


def test_upsert_excluded_increments_survive_concurrent_writers(
    isolated_db, capture_queries
):
    """Concurrent callers each add their own delta -- none is lost.

    The read and the write happen in one statement, under the row lock
    Postgres takes on the conflicting tuple, so there is no read-modify-write
    window for a second writer to slip into. The statement under test is the
    one upsert() actually emits, captured and then replayed from several real
    sessions at once (the test harness scopes its database to the main
    thread, so the racing sessions have to be raw connections).
    """
    workers = 8
    key = "concurrent-counter"
    table = UpsertItem.model_options.db_table

    with capture_queries() as queries:
        UpsertItem.query.upsert(
            key=key,
            value=1,
            conflict_defaults={"value": F("value") + Excluded("value")},
            unique_fields=[UpsertItem.key],
        )
    increment_sql = queries[0]["sql"]
    assert f'"value" = ("{table}"."value" + EXCLUDED."value")' in increment_sql

    params = build_connection_params(get_connection().settings_dict)
    barrier = threading.Barrier(workers)

    def race(_: int) -> None:
        with psycopg.connect(**params, autocommit=True) as session:
            barrier.wait()
            session.execute(increment_sql)

    # Start from the row that first upsert() inserted, then race the same
    # statement -- every session takes the conflict path.
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(race, range(workers)))

    assert UpsertItem.query.get(key=key).value == 1 + workers


def test_upsert_all_unique_fields_is_idempotent(db):
    # When every inserted column is a unique field there's nothing to update;
    # the second call must still return the existing row (created=False).
    obj1, created1 = Widget.query.upsert(
        name="Toyota", size="Tundra", unique_fields=[Widget.name, Widget.size]
    )
    obj2, created2 = Widget.query.upsert(
        name="Toyota", size="Tundra", unique_fields=[Widget.name, Widget.size]
    )

    assert created1 is True
    assert created2 is False
    assert obj1.id == obj2.id
    assert Widget.query.count() == 1


def test_upsert_conflicts_on_a_foreign_key(db):
    """`Model.fk` is the relation descriptor, not a Field, so a composite
    conflict target that includes a foreign key has to resolve it to the
    column. Static half: tests/typing/upsert_writes.py.
    """
    scope = UpsertScope(name="s").create()

    first, created = UpsertScopedItem.query.upsert(
        scope=scope,
        key="a",
        value=1,
        unique_fields=[UpsertScopedItem.scope, UpsertScopedItem.key],
    )
    assert created is True

    second, created = UpsertScopedItem.query.upsert(
        scope=scope,
        key="a",
        value=2,
        unique_fields=[UpsertScopedItem.scope, UpsertScopedItem.key],
    )
    assert created is False
    assert second.id == first.id
    assert second.value == 2
    assert UpsertScopedItem.query.count() == 1


def test_upsert_foreign_key_conflict_target_scopes_by_parent(db):
    """The same key under a different parent is a different row."""
    one = UpsertScope(name="one").create()
    two = UpsertScope(name="two").create()

    UpsertScopedItem.query.upsert(
        scope=one,
        key="a",
        value=1,
        unique_fields=[UpsertScopedItem.scope, UpsertScopedItem.key],
    )
    _, created = UpsertScopedItem.query.upsert(
        scope=two,
        key="a",
        value=2,
        unique_fields=[UpsertScopedItem.scope, UpsertScopedItem.key],
    )

    assert created is True
    assert UpsertScopedItem.query.count() == 2


def test_reverse_manager_upsert_conflicts_on_the_parent_key(db):
    """Through the reverse manager the parent is filled in automatically, so
    the conflict target still needs the foreign key column.
    """
    scope = UpsertScope(name="s").create()

    first, created = scope.entries.upsert(
        key="a",
        value=1,
        unique_fields=[UpsertScopedItem.scope, UpsertScopedItem.key],
    )
    assert created is True
    assert first.scope.id == scope.id

    second, created = scope.entries.upsert(
        key="a",
        value=5,
        unique_fields=[UpsertScopedItem.scope, UpsertScopedItem.key],
    )
    assert created is False
    assert second.id == first.id
    assert second.value == 5
    assert scope.entries.query.count() == 1


def test_upsert_conflict_defaults_rejects_a_many_to_many_field(db):
    """A many-to-many field is a forward field with no column of its own, so
    it passes the name lookup and used to fail in Postgres with a bare
    UndefinedColumn.
    """
    Widget.query.create(name="w", size="s")

    with pytest.raises(FieldError, match="only database columns can be set"):
        Widget.query.upsert(
            name="w",
            size="s",
            conflict_defaults={"tags": []},
            unique_fields=[Widget.name, Widget.size],
        )


def test_upsert_conflict_defaults_rejects_a_reverse_relation_name(db):
    with pytest.raises(FieldError, match="Invalid conflict_defaults field name"):
        Tag.query.upsert(
            name="t",
            conflict_defaults={"widgets": []},
            unique_fields=[Tag.name],
        )


def test_upsert_requires_unique_fields(db):
    with pytest.raises(ValueError, match="requires unique_fields"):
        UpsertItem.query.upsert(key="a", unique_fields=[])


def test_upsert_unique_fields_must_match_a_constraint(db):
    with pytest.raises(ValueError, match="must name the primary key"):
        UpsertItem.query.upsert(key="a", value=1, unique_fields=[UpsertItem.value])


def test_upsert_rejects_null_unique_value(db):
    with pytest.raises(ValueError, match="non-null"):
        UpsertItem.query.upsert(key=None, unique_fields=[UpsertItem.key])


def test_upsert_string_unique_field_rejected(db):
    with pytest.raises(TypeError, match="takes field references, not strings"):
        UpsertItem.query.upsert(
            key="a",
            value=1,
            unique_fields=["key"],  # ty: ignore[invalid-argument-type]
        )


def test_upsert_wrong_model_unique_field_rejected(db):
    with pytest.raises(FieldError, match="belongs to a different model"):
        UpsertItem.query.upsert(key="a", value=1, unique_fields=[Widget.name])


def test_upsert_conflict_defaults_accepts_related_instance(db):
    # A model instance as a conflict_defaults value exercises the related-field
    # branch of assignment-value compilation (prepare_database_save).
    owner = UpsertOwner(name="owner").create()
    UpsertItem(key="a", value=1).create()

    obj, created = UpsertItem.query.upsert(
        key="a",
        value=2,
        conflict_defaults={"owner": owner},
        unique_fields=[UpsertItem.key],
    )

    assert created is False
    assert obj.owner is not None
    assert obj.owner.id == owner.id
    reloaded = UpsertItem.query.get(key="a")
    assert reloaded.owner is not None
    assert reloaded.owner.id == owner.id


def test_upsert_bumps_update_now_on_conflict(db):
    """A DateTimeField(update_now=True) column nobody named still advances on
    the conflict path -- pre_save stamped it into the INSERT, so EXCLUDED
    carries it. A create_now-only column keeps its original value.
    """
    first, created = UpsertItem.query.upsert(
        key="a", value=1, unique_fields=[UpsertItem.key]
    )
    assert created is True

    second, created = UpsertItem.query.upsert(
        key="a", value=2, unique_fields=[UpsertItem.key]
    )
    assert created is False
    assert second.updated_at > first.updated_at
    assert second.created_at == first.created_at


def test_upsert_conflict_defaults_rejects_unique_field(db):
    with pytest.raises(ValueError, match="cannot name the unique field"):
        UpsertItem.query.upsert(
            key="a",
            conflict_defaults={"key": "b"},
            unique_fields=[UpsertItem.key],
        )


def test_upsert_conflict_defaults_rejects_unknown_field_name(db):
    with pytest.raises(FieldError, match="conflict_defaults"):
        UpsertItem.query.upsert(
            key="a",
            conflict_defaults={"typo_field": 1},
            unique_fields=[UpsertItem.key],
        )


def test_upsert_rejects_primary_key_unique_field(db):
    with pytest.raises(ValueError, match="cannot conflict on the primary key"):
        UpsertItem.query.upsert(key="a", unique_fields=[UpsertItem.id])


def test_upsert_rejects_unknown_field_name(db):
    with pytest.raises(FieldError, match="typo_field"):
        UpsertItem.query.upsert(
            key="a", defaults={"typo_field": 1}, unique_fields=[UpsertItem.key]
        )


def test_upsert_insert_is_one_statement(db, capture_queries):
    with capture_queries() as queries:
        UpsertItem.query.upsert(key="a", value=1, unique_fields=[UpsertItem.key])

    assert len(queries) == 1


def test_upsert_conflict_is_one_statement(db, capture_queries):
    UpsertItem(key="a", value=1).create()

    with capture_queries() as queries:
        UpsertItem.query.upsert(key="a", value=2, unique_fields=[UpsertItem.key])

    assert len(queries) == 1
