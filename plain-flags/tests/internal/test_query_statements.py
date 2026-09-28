"""The SQL a flag evaluation emits, pinned statement by statement.

The Flag row is claimed with one `INSERT ... ON CONFLICT DO UPDATE ...
RETURNING`. It used to be `update_or_create()`: a `SELECT ... FOR UPDATE`
followed by an INSERT or an UPDATE, inside a transaction. These pin the
statement list so a regression back to the read-then-write shape shows up as a
failing test rather than as extra round trips on every flag read.

The FlagResult statements that follow are a separate, unconverted
get_or_create() path -- they are pinned here only so the counts stay honest.
"""

from plain.flags import Flag
from plain.flags.models import Flag as FlagModel
from plain.postgres.test import span_sql_statements
from plain.test import capture_spans


class _PinnedFlag(Flag):
    def get_key(self) -> str:
        return "user-123"

    def get_value(self) -> bool:
        return True


def test_first_evaluation_creates_the_flag_in_one_statement() -> None:
    with capture_spans() as spans:
        assert _PinnedFlag().value is True

    sql = span_sql_statements(spans)
    assert len(sql) == 3
    assert sql[0].startswith('INSERT INTO "plainflags_flag"')
    assert 'ON CONFLICT("name") DO UPDATE SET' in sql[0]
    assert "RETURNING" in sql[0]
    # The FlagResult row is still a get_or_create(): SELECT, then INSERT.
    assert sql[1].startswith('SELECT "plainflags_flagresult"')
    assert sql[2].startswith('INSERT INTO "plainflags_flagresult"')

    assert not any("FOR UPDATE" in statement for statement in sql)


def test_second_evaluation_reuses_the_flag_in_one_statement() -> None:
    assert _PinnedFlag().value is True

    with capture_spans() as spans:
        assert _PinnedFlag().value is True

    sql = span_sql_statements(spans)
    assert len(sql) == 2
    assert sql[0].startswith('INSERT INTO "plainflags_flag"')
    assert 'ON CONFLICT("name") DO UPDATE SET' in sql[0]
    assert "RETURNING" in sql[0]
    # The FlagResult row already exists, so get_or_create() only reads.
    assert sql[1].startswith('SELECT "plainflags_flagresult"')

    assert not any("FOR UPDATE" in statement for statement in sql)


def test_conflict_refreshes_timestamps_and_leaves_the_rest_alone() -> None:
    assert _PinnedFlag().value is True
    FlagModel.query.filter(name="_PinnedFlag").update(
        enabled=False, description="still in use"
    )

    with capture_spans() as spans:
        # A disabled flag returns None, but it still claims its row.
        assert _PinnedFlag().value is None

    insert = next(s for s in span_sql_statements(spans) if s.startswith("INSERT"))
    set_clause = insert.split("DO UPDATE SET")[1].split(" RETURNING ")[0]
    assert '"used_at" = EXCLUDED."used_at"' in set_clause
    assert '"updated_at" = EXCLUDED."updated_at"' in set_clause
    # The INSERT proposes defaults for these, but a conflict must not apply
    # them -- an operator's enabled/description edits have to survive.
    assert '"enabled"' not in set_clause
    assert '"description"' not in set_clause
    assert '"created_at"' not in set_clause

    row = FlagModel.query.get(name="_PinnedFlag")
    assert row.enabled is False
    assert row.description == "still in use"
