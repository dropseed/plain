"""Constraints created by an earlier plain-postgres hold doubled `%` literals.

`quote_value` used to double `%` for a parameter substitution the DDL never
went through, so a model's `'100%'` was stored as `'100%%'`. Now that the
literal is written as is, convergence meets the old definition in every
existing database. It must replace it under the same name, not block sync
the way a real definition change does.
"""

import psycopg.sql
from app.examples.models.describe import DescribedPerson
from convergence_helpers import constraint_is_valid, execute, index_exists
from plain.postgres import ddl, get_connection
from plain.postgres.convergence import execute_plan, plan_model_convergence
from plain.postgres.convergence.analysis import (
    ConstraintModelDrift,
    ConstraintPercentDrift,
)
from plain.postgres.convergence.corrections import ReplaceConstraintCorrection
from plain.postgres.testing import isolated_db
from plain.testing import patch

TABLE = "examples_describedperson"
CHECK = "describedperson_name_not_100pct_check"
PARTIAL_UNIQUE = "describedperson_name_unique_unless_pct"


def _quote_value_doubling_percent(value: object) -> str:
    """`quote_value` as it was."""
    if isinstance(value, str):
        value = value.replace("%", "%%")
    return psycopg.sql.quote(value, get_connection().connection)


def _declared(name: str):
    return next(c for c in DescribedPerson.model_options.constraints if c.name == name)


def _stage_old_definition(name: str, *, index_only: bool) -> None:
    """Swap the live constraint for the one the old quoting produced."""
    if index_only:
        execute(f'DROP INDEX "{name}"')
    else:
        execute(f'ALTER TABLE "{TABLE}" DROP CONSTRAINT "{name}"')
    with patch(ddl, "quote_value", _quote_value_doubling_percent):
        old_sql = _declared(name).to_sql(DescribedPerson)
    execute(old_sql)


def _plan():
    conn = get_connection()
    with conn.cursor() as cursor:
        return plan_model_convergence(conn, cursor, DescribedPerson)


def _item_for(plan, name: str):
    return next(
        item
        for item in plan.items
        if getattr(item.drift, "constraint", None) is not None
        and item.drift.constraint.name == name
    )


def _check_definition() -> str:
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
            [CHECK],
        )
        row = cursor.fetchone()
        assert row is not None
        return row[0]


@isolated_db
def test_doubled_percent_in_a_check_is_replaced_not_blocked():
    _stage_old_definition(CHECK, index_only=False)
    assert "'100%%'" in _check_definition()

    item = _item_for(_plan(), CHECK)
    assert isinstance(item.drift, ConstraintPercentDrift)
    assert isinstance(item.correction, ReplaceConstraintCorrection)
    assert item.blocks_sync is True  # a failed replacement must stop sync

    result = execute_plan([item])
    assert all(r.ok for r in result.results)
    assert "'100%'" in _check_definition()
    assert constraint_is_valid(TABLE, CHECK)
    assert not any(
        getattr(i.drift, "constraint", None) is not None
        and i.drift.constraint.name == CHECK
        for i in _plan().items
    )


@isolated_db
def test_doubled_percent_in_a_partial_unique_is_replaced_not_blocked():
    _stage_old_definition(PARTIAL_UNIQUE, index_only=True)

    item = _item_for(_plan(), PARTIAL_UNIQUE)
    assert isinstance(item.drift, ConstraintPercentDrift)
    assert isinstance(item.correction, ReplaceConstraintCorrection)
    assert item.blocks_sync is True  # a failed replacement must stop sync

    result = execute_plan([item])
    assert all(r.ok for r in result.results)
    assert index_exists(PARTIAL_UNIQUE)
    assert not any(
        getattr(i.drift, "constraint", None) is not None
        and i.drift.constraint.name == PARTIAL_UNIQUE
        for i in _plan().items
    )


@isolated_db
def test_a_genuinely_changed_check_still_blocks():
    execute(f'ALTER TABLE "{TABLE}" DROP CONSTRAINT "{CHECK}"')
    execute(
        f'ALTER TABLE "{TABLE}" ADD CONSTRAINT "{CHECK}" CHECK (NOT ("name" = \'200%\'))'
    )

    item = _item_for(_plan(), CHECK)
    assert isinstance(item.drift, ConstraintModelDrift)
    assert item.correction is None
    assert item.blocks_sync is True
