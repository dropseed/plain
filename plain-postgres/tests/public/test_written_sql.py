"""`Model.query.sql()` — written queries.

The contract: what a `{}` reference renders as, what a row comes back as, and
what a statement refuses. The static half lives in tests/typing/written_sql.py.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

import pytest
from app.examples.models.encrypted import SecretStore
from app.examples.models.mixins import MixinTestModel
from app.examples.models.relationships import Tag, Widget, WidgetTag
from app.examples.models.returning import ReturningEvent
from plain.exceptions import ValidationError
from plain.postgres import Fragment


@pytest.fixture
def widgets(db):
    small = Widget.query.create(name="small-widget", size="small")
    large = Widget.query.create(name="large-widget", size="large")
    red = Tag.query.create(name="red")
    blue = Tag.query.create(name="blue")
    WidgetTag.query.create(widget=small, tag=red)
    WidgetTag.query.create(widget=small, tag=blue)
    WidgetTag.query.create(widget=large, tag=red)
    return small, large


@dataclass
class SizeCount:
    size: str
    n: int


# ---------------------------------------------------------------------------
# The interpolation table
# ---------------------------------------------------------------------------


def test_model_reference_renders_the_table(widgets):
    rows = Widget.query.sql("SELECT count(*) AS n FROM {Widget}", result_type=SizeCount)
    assert '"widget"' in rows.sql or Widget.model_options.db_table in rows.sql


def test_field_reference_renders_the_qualified_column(widgets):
    statement = Widget.query.sql(
        """
        SELECT {Widget.size} AS size, count(*) AS n
        FROM {Widget}
        GROUP BY 1
        ORDER BY 1
        """,
        result_type=SizeCount,
    )
    table = Widget.model_options.db_table
    assert f'"{table}"."size"' in statement.sql
    assert statement.all() == [
        SizeCount(size="large", n=1),
        SizeCount(size="small", n=1),
    ]


def test_foreign_key_reference_renders_the_id_column(widgets):
    small, _ = widgets
    table = WidgetTag.model_options.db_table

    @dataclass
    class TagCount:
        widget_id: int
        n: int

    statement = WidgetTag.query.sql(
        """
        SELECT {WidgetTag.widget} AS widget_id, count(*) AS n
        FROM {WidgetTag}
        WHERE {WidgetTag.widget} = {widget_id}
        GROUP BY 1
        """,
        widget_id=small.id,
        result_type=TagCount,
    )
    assert f'"{table}"."widget_id"' in statement.sql
    assert statement.get() == TagCount(widget_id=small.id, n=2)


def test_star_reference_returns_model_instances(widgets):
    statement = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size}",
        size="small",
    )
    widget = statement.get()
    assert isinstance(widget, Widget)
    assert widget.name == "small-widget"
    assert widget._state.adding is False


def test_value_binds_as_a_parameter(widgets):
    statement = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.name} = {name}",
        name="small-widget",
    )
    assert "%s" in statement.sql
    assert statement.params == ("small-widget",)
    assert statement.get().name == "small-widget"


def test_a_value_used_twice_binds_twice(widgets):
    statement = Widget.query.sql(
        """
        SELECT {Widget.*} FROM {Widget}
        WHERE {Widget.name} = {name} OR {Widget.size} = {name}
        """,
        name="small",
    )
    assert statement.params == ("small", "small")
    assert statement.get().name == "small-widget"


def test_list_binds_as_an_array_for_any(widgets):
    statement = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.name} = ANY({names}) ORDER BY 1",
        names=["small-widget", "large-widget"],
    )
    assert len(statement.all()) == 2


def test_dict_binds_as_jsonb(db):
    ReturningEvent.query.create(label="signup", count=1, payload={"plan": "pro"})
    ReturningEvent.query.create(label="churn", count=1, payload={"plan": "free"})

    statement = ReturningEvent.query.sql(
        "SELECT {ReturningEvent.*} FROM {ReturningEvent} WHERE {ReturningEvent.payload} @> {match}",
        match={"plan": "pro"},
    )
    event = statement.get()
    assert event.label == "signup"
    assert event.payload == {"plan": "pro"}


def test_fragment_inlines_its_text(widgets):
    small_only = Fragment("size = 'small'")
    statement = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {predicate}",
        predicate=small_only,
    )
    assert "size = 'small'" in statement.sql
    assert statement.get().name == "small-widget"


def test_fragment_refuses_a_non_literal():
    text = "size = 'small'"
    with pytest.raises(TypeError, match="string literal"):
        Fragment(text)
    with pytest.raises(TypeError, match="string literal"):
        Fragment(f"size = '{text}'")


def test_embedded_queryset_becomes_a_subquery(widgets):
    small_widgets = Widget.query.where(Widget.size.equals("small"))

    @dataclass
    class NameRow:
        name: str

    statement = Widget.query.sql(
        'SELECT sub."name" AS name FROM {small} sub ORDER BY 1',
        small=small_widgets,
        result_type=NameRow,
    )
    assert statement.all() == [NameRow(name="small-widget")]
    assert statement.params == ("small",)


def test_embedded_queryset_with_no_rows_still_renders(widgets):
    nothing = Widget.query.where(Widget.name.is_in([]))

    @dataclass
    class NameRow:
        name: str

    statement = Widget.query.sql(
        'SELECT sub."name" AS name FROM {nothing} sub',
        nothing=nothing,
        result_type=NameRow,
    )
    assert statement.all() == []


def test_written_embeds_in_another_written(widgets):
    @dataclass
    class NameRow:
        name: str

    inner = Widget.query.sql(
        "SELECT {Widget.name} AS name FROM {Widget} WHERE {Widget.size} = {size}",
        size="small",
        result_type=NameRow,
    )
    outer = Widget.query.sql(
        "SELECT sub.name AS name FROM {inner} sub",
        inner=inner,
        result_type=NameRow,
    )
    assert outer.params == ("small",)
    assert outer.all() == [NameRow(name="small-widget")]


def test_a_literal_percent_survives(widgets):
    @dataclass
    class NameRow:
        name: str

    statement = Widget.query.sql(
        "SELECT {Widget.name} AS name FROM {Widget} WHERE {Widget.name} LIKE {pattern} || '%'",
        pattern="small",
        result_type=NameRow,
    )
    assert statement.all() == [NameRow(name="small-widget")]


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


def test_instances_decrypt_and_parse_their_fields(db):
    SecretStore.query.create(
        name="prod", api_key="sk-live-123", notes="top secret", config={"a": 1}
    )
    statement = SecretStore.query.sql(
        "SELECT {SecretStore.*} FROM {SecretStore}",
    )
    secret = statement.get()
    assert secret.api_key == "sk-live-123"
    assert secret.notes == "top secret"
    assert secret.config == {"a": 1}


def test_extra_columns_become_attributes(widgets):
    statement = Widget.query.sql(
        """
        SELECT {Widget.*}, count(wt.id) AS tag_count
        FROM {Widget}
        LEFT JOIN {WidgetTag} wt ON wt.widget_id = {Widget.id}
        GROUP BY {Widget.id}
        ORDER BY {Widget.name}
        """,
    )
    rows = statement.all()
    assert [(w.name, getattr(w, "tag_count")) for w in rows] == [
        ("large-widget", 1),
        ("small-widget", 2),
    ]


def test_result_type_maps_columns_by_name(widgets):
    statement = Widget.query.sql(
        """
        SELECT count(*) AS n, {Widget.size} AS size
        FROM {Widget}
        GROUP BY 2
        ORDER BY 2
        """,
        result_type=SizeCount,
    )
    assert statement.all() == [
        SizeCount(size="large", n=1),
        SizeCount(size="small", n=1),
    ]


def test_alias_markers_are_stripped(db):
    """`AS "n!"` and `AS "oldest?"` map onto `n` and `oldest`."""
    MixinTestModel.query.create(name="one")
    MixinTestModel.query.create(name="one")

    @dataclass
    class Stats:
        name: str
        n: int
        oldest: datetime.datetime | None

    statement = MixinTestModel.query.sql(
        """
        SELECT {MixinTestModel.name} AS name,
               count(*) AS "n!",
               min({MixinTestModel.created_at}) AS "oldest?"
        FROM {MixinTestModel}
        GROUP BY 1
        """,
        result_type=Stats,
    )
    row = statement.get()
    assert row.name == "one"
    assert row.n == 2
    assert isinstance(row.oldest, datetime.datetime)


def test_result_type_converters_run(db):
    SecretStore.query.create(name="prod", api_key="sk-live-123", config={"a": 1})

    @dataclass
    class SecretRow:
        name: str
        api_key: str
        config: dict

    statement = SecretStore.query.sql(
        """
        SELECT {SecretStore.name} AS name,
               {SecretStore.api_key} AS api_key,
               {SecretStore.config} AS config
        FROM {SecretStore}
        """,
        result_type=SecretRow,
    )
    assert statement.get() == SecretRow(
        name="prod", api_key="sk-live-123", config={"a": 1}
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def test_get_first_count_exists(widgets):
    statement = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} ORDER BY {Widget.name}",
    )
    assert statement.count() == 2
    assert statement.exists() is True
    first = statement.first()
    assert first is not None
    assert first.name == "large-widget"

    one = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size}", size="small"
    )
    assert one.get().name == "small-widget"


def test_get_raises_the_models_exceptions(widgets):
    none = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size}", size="nope"
    )
    with pytest.raises(Widget.DoesNotExist):
        none.get()

    both = Widget.query.sql("SELECT {Widget.*} FROM {Widget}")
    with pytest.raises(Widget.MultipleObjectsReturned):
        both.get()


def test_get_on_a_row_statement_raises_value_error(widgets):
    statement = Widget.query.sql(
        "SELECT {Widget.size} AS size, count(*) AS n FROM {Widget} GROUP BY 1",
        result_type=SizeCount,
    )
    with pytest.raises(ValueError, match="2 rows"):
        statement.get()


def test_exists_is_false_on_no_rows(widgets):
    statement = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size}", size="nope"
    )
    assert statement.exists() is False
    assert statement.count() == 0
    assert statement.first() is None
    assert list(statement) == []


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def test_write_with_returning_gives_instances(widgets):
    statement = Widget.query.sql(
        """
        UPDATE {Widget} SET "size" = {size}
        WHERE {Widget.name} = {name}
        RETURNING {Widget.*}
        """,
        size="medium",
        name="small-widget",
    )
    updated = statement.get()
    assert isinstance(updated, Widget)
    assert updated.size == "medium"
    assert Widget.query.get(name="small-widget").size == "medium"


def test_write_without_returning_gives_a_row_count(widgets):
    statement = Widget.query.sql(
        'UPDATE {Widget} SET "size" = {size} WHERE {Widget.size} = {old}',
        size="tiny",
        old="small",
    )
    assert statement.execute() == 1
    assert list(statement) == []
    assert Widget.query.filter(size="tiny").count() == 1


def test_execute_counts_rows_without_shaping_them(widgets):
    """A write can RETURNING without saying what a row is; execute() counts."""
    statement = Widget.query.sql(
        "DELETE FROM {Widget} WHERE {Widget.size} = {size} RETURNING {Widget.id}",
        size="small",
    )
    assert statement.execute() == 1
    assert statement.count() == 1
    assert Widget.query.filter(size="small").count() == 0


def test_insert_returning_a_result_type(db):
    @dataclass
    class NewWidget:
        id: int
        name: str

    statement = Widget.query.sql(
        """
        INSERT INTO {Widget} ("name", "size") VALUES ({name}, {size})
        RETURNING {Widget.id} AS id, {Widget.name} AS name
        """,
        name="fresh",
        size="small",
        result_type=NewWidget,
    )
    row = statement.get()
    assert row.name == "fresh"
    assert Widget.query.get(id=row.id).name == "fresh"


def test_constraint_violation_maps_to_validation_error(widgets):
    statement = Tag.query.sql(
        'INSERT INTO {Tag} ("name") VALUES ({name})',
        name="red",  # unique_tag_name already holds "red"
    )
    with pytest.raises(ValidationError):
        statement.execute()


def test_a_statement_runs_once(widgets):
    statement = Widget.query.sql(
        """
        INSERT INTO {Widget} ("name", "size") VALUES ({name}, {size})
        RETURNING {Widget.*}
        """,
        name="once",
        size="small",
    )
    first = statement.all()
    second = statement.all()
    assert first == second
    assert Widget.query.filter(name="once").count() == 1


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_unknown_model_reference(db):
    with pytest.raises(ValueError, match="names no model"):
        Widget.query.sql("SELECT * FROM {Nonexistent}")


def test_unknown_field_reference(db):
    with pytest.raises(ValueError, match="no field on Widget"):
        Widget.query.sql("SELECT {Widget.nope} FROM {Widget}")


def test_missing_value(db):
    with pytest.raises(ValueError, match="has no value and names no model"):
        Widget.query.sql("SELECT * FROM {Widget} WHERE size = {size}")


def test_multiple_statements_are_refused(db):
    with pytest.raises(ValueError, match="single statement"):
        Widget.query.sql("SELECT 1; DROP TABLE {Widget}")


def test_a_semicolon_inside_a_string_is_fine(widgets):
    @dataclass
    class NameRow:
        name: str

    statement = Widget.query.sql(
        "SELECT {Widget.name} AS name FROM {Widget} WHERE {Widget.name} <> 'a;b'",
    )
    assert statement is not None


def test_result_type_must_be_a_dataclass(db):
    with pytest.raises(TypeError, match="requires a dataclass"):
        Widget.query.sql(  # ty: ignore[no-matching-overload]
            "SELECT 1 AS n FROM {Widget}", result_type=int
        )


def test_star_and_result_type_together_are_refused(db):
    with pytest.raises(TypeError, match="not both"):
        Widget.query.sql("SELECT {Widget.*} FROM {Widget}", result_type=SizeCount)


def test_rows_with_no_result_type_are_refused(widgets):
    statement = Widget.query.sql("SELECT {Widget.size} AS size FROM {Widget}")
    with pytest.raises(TypeError, match="result_type"):
        statement.all()


def test_result_type_column_mismatch(widgets):
    @dataclass
    class Wrong:
        size: str
        missing: int

    statement = Widget.query.sql(
        "SELECT {Widget.size} AS size FROM {Widget}", result_type=Wrong
    )
    with pytest.raises(TypeError, match="no column for missing"):
        statement.all()


def test_result_type_type_mismatch(widgets):
    @dataclass
    class Wrong:
        size: Decimal
        n: int

    statement = Widget.query.sql(
        "SELECT {Widget.size} AS size, count(*) AS n FROM {Widget} GROUP BY 1",
        result_type=Wrong,
    )
    with pytest.raises(TypeError, match="comes back as str"):
        statement.all()
