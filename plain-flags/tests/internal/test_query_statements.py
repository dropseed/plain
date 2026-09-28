"""The SQL a flag evaluation emits, pinned statement by statement.

The Flag row is claimed with one `INSERT ... ON CONFLICT DO UPDATE ...
RETURNING`. It used to be `update_or_create()`: a `SELECT ... FOR UPDATE`
followed by an INSERT or an UPDATE, inside a transaction. These pin the
statement list so a regression back to the read-then-write shape shows up as a
failing test rather than as extra round trips on every flag read.

The FlagResult statements that follow are a separate, unconverted
get_or_create() path -- they are pinned here only so the counts stay honest.
"""

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from plain.flags import Flag
from plain.flags.models import Flag as FlagModel


class _PinnedFlag(Flag):
    def get_key(self) -> str:
        return "user-123"

    def get_value(self) -> bool:
        return True


def statements(otel_spans: InMemorySpanExporter) -> list[str]:
    """Every SQL statement the captured spans carry, in the order it ran."""
    return [
        " ".join(str(span.attributes["db.query.text"]).split())
        for span in otel_spans.get_finished_spans()
        if span.attributes and "db.query.text" in span.attributes
    ]


def test_first_evaluation_creates_the_flag_in_one_statement(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    otel_spans.clear()
    assert _PinnedFlag().value is True

    sql = statements(otel_spans)
    assert len(sql) == 3
    assert sql[0].startswith('INSERT INTO "plainflags_flag"')
    assert 'ON CONFLICT("name") DO UPDATE SET' in sql[0]
    assert "RETURNING" in sql[0]
    # The FlagResult row is still a get_or_create(): SELECT, then INSERT.
    assert sql[1].startswith('SELECT "plainflags_flagresult"')
    assert sql[2].startswith('INSERT INTO "plainflags_flagresult"')

    assert not any("FOR UPDATE" in statement for statement in sql)


def test_second_evaluation_reuses_the_flag_in_one_statement(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    assert _PinnedFlag().value is True

    otel_spans.clear()
    assert _PinnedFlag().value is True

    sql = statements(otel_spans)
    assert len(sql) == 2
    assert sql[0].startswith('INSERT INTO "plainflags_flag"')
    assert 'ON CONFLICT("name") DO UPDATE SET' in sql[0]
    assert "RETURNING" in sql[0]
    # The FlagResult row already exists, so get_or_create() only reads.
    assert sql[1].startswith('SELECT "plainflags_flagresult"')

    assert not any("FOR UPDATE" in statement for statement in sql)


def test_conflict_refreshes_timestamps_and_leaves_the_rest_alone(
    db: None, otel_spans: InMemorySpanExporter
) -> None:
    assert _PinnedFlag().value is True
    FlagModel.query.filter(name="_PinnedFlag").update(
        enabled=False, description="still in use"
    )

    otel_spans.clear()
    # A disabled flag returns None, but it still claims its row.
    assert _PinnedFlag().value is None

    insert = next(s for s in statements(otel_spans) if s.startswith("INSERT"))
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
