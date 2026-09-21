"""`Model.query.sql()` — written queries.

The contract: what a `{}` reference renders as, what a row comes back as, and
what a statement refuses. The static half lives in tests/typing/written_sql.py,
and the literal-template rule is `plain preflight`'s
(tests/internal/test_written_preflight.py).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

import psycopg
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


@dataclass
class NameRow:
    name: str


# ---------------------------------------------------------------------------
# The interpolation table
# ---------------------------------------------------------------------------


def test_model_reference_renders_the_table(widgets):
    statement = Widget.query.sql(
        "SELECT count(*) AS n FROM {Widget}", result_type=SizeCount
    )
    assert f'"{Widget.model_options.db_table}"' in statement.sql


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


def test_bare_column_reference_renders_the_column_alone(widgets):
    """`{Model.field:name}` is the spelling an INSERT list needs."""
    statement = Widget.query.sql(
        """
        INSERT INTO {Widget} ({Widget.name:name}, {Widget.size:name})
        VALUES ({name}, {size})
        RETURNING {Widget.*}
        """,
        name="fresh",
        size="tiny",
    )
    assert '("name", "size")' in statement.sql
    assert statement.get().name == "fresh"


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
        "SELECT {ReturningEvent.*} FROM {ReturningEvent} "
        "WHERE {ReturningEvent.payload} @> {match}",
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


def test_fragment_requires_a_string():
    with pytest.raises(TypeError, match="string literal"):
        Fragment(42)  # ty: ignore[invalid-argument-type]


def test_embedded_queryset_becomes_a_subquery(widgets):
    small_widgets = Widget.query.where(Widget.size.equals("small"))

    statement = Widget.query.sql(
        'SELECT sub."name" AS name FROM {small} sub ORDER BY 1',
        small=small_widgets,
        result_type=NameRow,
    )
    assert statement.all() == [NameRow(name="small-widget")]
    assert statement.params == ("small",)


def test_embedded_queryset_with_no_rows_still_renders(widgets):
    nothing = Widget.query.where(Widget.name.is_in([]))

    statement = Widget.query.sql(
        'SELECT sub."name" AS name FROM {nothing} sub',
        nothing=nothing,
        result_type=NameRow,
    )
    assert statement.all() == []


def test_written_embeds_in_another_written(widgets):
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


def test_a_literal_percent_survives_and_stays_readable(widgets):
    statement = Widget.query.sql(
        "SELECT {Widget.name} AS name FROM {Widget} "
        "WHERE {Widget.name} LIKE {pattern} || '%'",
        pattern="small",
        result_type=NameRow,
    )
    # `.sql` is the statement as written -- the doubling psycopg needs to bind
    # parameters is not something to read.
    assert "|| '%'" in statement.sql
    assert "%%" not in statement.sql
    assert statement.all() == [NameRow(name="small-widget")]


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


def test_instances_decrypt_and_parse_their_fields(db):
    SecretStore.query.create(
        name="prod", api_key="sk-live-123", notes="top secret", config={"a": 1}
    )
    statement = SecretStore.query.sql("SELECT {SecretStore.*} FROM {SecretStore}")
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


def test_a_repeated_column_is_kept_as_an_extra(widgets):
    """`{Widget.*}` and `{Widget.name}` in one statement: both arrive."""
    statement = Widget.query.sql(
        """
        SELECT {Widget.*}, upper({Widget.name}) AS display_name
        FROM {Widget}
        WHERE {Widget.size} = {size}
        """,
        size="small",
    )
    widget = statement.get()
    assert widget.name == "small-widget"
    assert getattr(widget, "display_name") == "SMALL-WIDGET"


def test_a_self_join_hydrates_the_row_it_selected(widgets):
    """The instance is `{Widget.*}`'s columns, not whatever traces to Widget.

    Both sides of a self-join trace back to the same table, so picking the
    instance's columns by provenance would mix the two rows together.
    """
    Widget.query.create(name="other-small", size="small")
    small = Widget.query.get(name="small-widget")

    statement = Widget.query.sql(
        """
        SELECT {Widget.*}, other."name" AS other_name
        FROM {Widget}
        JOIN {Widget} other
          ON other."size" = {Widget.size} AND other."id" <> {Widget.id}
        WHERE {Widget.name} = {name}
        """,
        name="small-widget",
    )
    widget = statement.get()
    assert widget.id == small.id
    assert widget.name == "small-widget"
    assert getattr(widget, "other_name") == "other-small"


def test_star_columns_work_through_a_union(widgets):
    """A UNION drops every column's source; the expansion still says what a row is."""
    statement = Widget.query.sql(
        """
        SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {small}
        UNION ALL
        SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {large}
        """,
        small="small",
        large="large",
    )
    names = sorted(widget.name for widget in statement)
    assert names == ["large-widget", "small-widget"]
    assert all(isinstance(widget, Widget) for widget in statement)


def test_an_unaliased_duplicate_column_is_refused(widgets):
    statement = Widget.query.sql(
        """
        SELECT {Widget.*}, other."name"
        FROM {Widget}
        JOIN {Widget} other ON other."id" <> {Widget.id}
        """,
    )
    with pytest.raises(TypeError, match="Alias the extra column"):
        statement.all()


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


def test_json_is_parsed_even_without_a_field(db):
    """`jsonb` is loaded as text and parsed by a converter — including here."""

    @dataclass
    class JsonRow:
        payload: dict

    statement = ReturningEvent.query.sql(
        "SELECT jsonb_build_object('a', {value}::int) AS payload",
        value=1,
        result_type=JsonRow,
    )
    assert statement.get() == JsonRow(payload={"a": 1})


def test_a_result_type_field_with_a_default_need_not_be_selected(widgets):
    @dataclass
    class PartialRow:
        name: str
        note: str = "unset"
        tags: list[str] = field(default_factory=list)

    statement = Widget.query.sql(
        "SELECT {Widget.name} AS name FROM {Widget} ORDER BY 1",
        result_type=PartialRow,
    )
    assert statement.first() == PartialRow(name="large-widget")


def test_an_encrypted_column_that_lost_its_source_is_refused(db):
    """Nothing can decrypt a column whose source an expression threw away."""
    SecretStore.query.create(name="prod", api_key="sk-live-123")

    @dataclass
    class SecretRow:
        api_key: str

    statement = SecretStore.query.sql(
        "SELECT coalesce({SecretStore.api_key}, '') AS api_key FROM {SecretStore}",
        result_type=SecretRow,
    )
    with pytest.raises(TypeError, match="nothing can decrypt it"):
        statement.all()


def test_prefetch_loads_related_objects(widgets, capture_queries, executed_sql):
    statement = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} ORDER BY {Widget.name}"
    ).prefetch("tags")

    with capture_queries() as queries:
        rows = statement.all()
        tags = [sorted(tag.name for tag in widget.tags.query) for widget in rows]

    assert tags == [["red"], ["blue", "red"]]
    assert len(queries) == 2  # the statement, and one prefetch


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
        UPDATE {Widget} SET {Widget.size:name} = {size}
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
        "UPDATE {Widget} SET {Widget.size:name} = {size} WHERE {Widget.size} = {old}",
        size="tiny",
        old="small",
    )
    assert statement.execute() == 1
    assert list(statement) == []
    assert Widget.query.filter(size="tiny").count() == 1


def test_asking_a_resultless_write_about_rows_is_refused(widgets):
    """0 would read like "the UPDATE matched nothing"."""
    statement = Widget.query.sql(
        "UPDATE {Widget} SET {Widget.size:name} = {size}", size="tiny"
    )
    with pytest.raises(TypeError, match="use execute\\(\\)"):
        statement.count()
    with pytest.raises(TypeError, match="use execute\\(\\)"):
        statement.exists()
    with pytest.raises(TypeError, match="use execute\\(\\)"):
        bool(statement)
    # ...and it still ran exactly once.
    assert Widget.query.filter(size="tiny").count() == 2


def test_execute_counts_rows_without_shaping_them(widgets):
    """A write can RETURNING without saying what a row is; execute() counts."""
    statement = Widget.query.sql(
        "DELETE FROM {Widget} WHERE {Widget.size} = {size} RETURNING {Widget.id}",
        size="small",
    )
    assert statement.execute() == 1
    assert statement.count() == 1
    assert Widget.query.filter(size="small").count() == 0


def test_a_write_runs_once_however_it_is_asked(widgets):
    """count()/first()/get() never run a write a second time."""
    statement = Widget.query.sql(
        """
        INSERT INTO {Widget} ({Widget.name:name}, {Widget.size:name})
        VALUES ({name}, {size})
        RETURNING {Widget.*}
        """,
        name="once",
        size="small",
    )
    assert statement.count() == 1
    assert statement.first() is not None
    assert statement.all() == statement.all()
    assert Widget.query.filter(name="once").count() == 1


def test_insert_returning_a_result_type(db):
    @dataclass
    class NewWidget:
        id: int
        name: str

    statement = Widget.query.sql(
        """
        INSERT INTO {Widget} ({Widget.name:name}, {Widget.size:name})
        VALUES ({name}, {size})
        RETURNING {Widget.id} AS id, {Widget.name} AS name
        """,
        name="fresh",
        size="small",
        result_type=NewWidget,
    )
    row = statement.get()
    assert row.name == "fresh"
    assert Widget.query.get(id=row.id).name == "fresh"


def test_unique_violation_maps_to_validation_error(widgets):
    """Any model's constraint maps, not just the queryset's own."""
    statement = Widget.query.sql(
        "INSERT INTO {Tag} ({Tag.name:name}) VALUES ({name})",
        name="red",  # unique_tag_name already holds "red"
    )
    with pytest.raises(ValidationError):
        statement.execute()


def test_foreign_key_violation_maps_to_validation_error(widgets):
    small, _ = widgets
    statement = WidgetTag.query.sql(
        """
        INSERT INTO {WidgetTag} ({WidgetTag.widget:name}, {WidgetTag.tag:name})
        VALUES ({widget_id}, {tag_id})
        """,
        widget_id=small.id,
        tag_id=999_999,
    )
    with pytest.raises(ValidationError):
        statement.execute()


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


def test_a_literal_brace_has_to_be_doubled(db):
    with pytest.raises(ValueError, match=r"is written `\{\{`"):
        Widget.query.sql("SELECT {Widget.*} FROM {Widget} WHERE name ~ '^a{2}'")


def test_a_trailing_semicolon_is_dropped(widgets):
    statement = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size};",
        size="small",
    )
    assert statement.get().name == "small-widget"


def test_a_second_statement_is_refused_when_a_parameter_binds(widgets):
    """With a parameter the statement goes over the extended protocol."""
    statement = Widget.query.sql(
        "SELECT {Widget.id} FROM {Widget} WHERE {Widget.size} = {size}; "
        "DELETE FROM {Widget}",
        size="small",
    )
    with pytest.raises(psycopg.errors.SyntaxError, match="multiple commands"):
        statement.execute()


def test_a_second_statement_is_refused_without_parameters(widgets):
    """With nothing to bind psycopg sends a simple query, which would run both."""
    with pytest.raises(ValueError, match="single statement"):
        Widget.query.sql("SELECT 1 AS n; DELETE FROM {Widget}")
    assert Widget.query.count() == 2


def test_sql_needs_a_bare_queryset(db):
    with pytest.raises(TypeError, match="where\\(\\)/filter\\(\\)"):
        Widget.query.where(Widget.size.equals("small")).sql(
            "SELECT {Widget.*} FROM {Widget}"
        )
    with pytest.raises(TypeError, match="order_by"):
        Widget.query.order_by("name").sql("SELECT {Widget.*} FROM {Widget}")
    with pytest.raises(TypeError, match="slicing"):
        Widget.query.all()[:2].sql("SELECT {Widget.*} FROM {Widget}")


def test_result_type_must_be_a_dataclass(db):
    with pytest.raises(TypeError, match="requires a dataclass"):
        Widget.query.sql(  # ty: ignore[no-matching-overload]
            "SELECT 1 AS n FROM {Widget}", result_type=int
        )


def test_a_star_inside_a_subquery_is_just_columns(widgets):
    """`result_type=` says what a row is; a `{Model.*}` below it is columns."""
    statement = Widget.query.sql(
        """
        SELECT count(*) AS n, {Widget.size} AS size
        FROM (SELECT {Widget.*} FROM {Widget}) AS {Widget}
        GROUP BY 2
        ORDER BY 2
        """,
        result_type=SizeCount,
    )
    assert statement.all() == [
        SizeCount(size="large", n=1),
        SizeCount(size="small", n=1),
    ]


def test_a_star_that_cannot_be_found_says_where_to_look(widgets):
    statement = Widget.query.sql(
        "SELECT count(*) AS n FROM (SELECT {Widget.*} FROM {Widget}) sub"
    )
    with pytest.raises(TypeError, match="inside a subquery"):
        statement.all()


def test_two_models_starred_are_refused(db):
    with pytest.raises(TypeError, match="more than one model"):
        Widget.query.sql(
            "SELECT {Widget.*}, {Tag.*} FROM {Widget}, {Tag}",
        )


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


def test_the_plan_follows_the_columns_not_the_template(widgets):
    """The same template with a different subquery is a different statement."""
    template = 'SELECT sub."name" AS name FROM {rows} sub ORDER BY 1'

    names = Widget.query.sql(
        template, rows=Widget.query.values("name"), result_type=NameRow
    )
    assert names.all() == [NameRow(name="large-widget"), NameRow(name="small-widget")]

    sizes = Widget.query.sql(
        template, rows=Widget.query.values("size"), result_type=NameRow
    )
    with pytest.raises(psycopg.errors.UndefinedColumn):
        sizes.all()


def test_a_trailing_comment_survives_the_row_limit(widgets):
    """first()/get()/count() wrap the statement; a `-- comment` can't swallow it."""
    statement = Widget.query.sql(
        """
        SELECT {Widget.*} FROM {Widget} ORDER BY {Widget.name}
        -- the oldest one
        """
    )
    first = statement.first()
    assert first is not None
    assert first.name == "large-widget"
    assert statement.count() == 2


def test_a_trailing_semicolon_is_dropped_from_the_sql_too(widgets):
    statement = Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size};  ",
        size="small",
    )
    assert not statement.sql.rstrip().endswith(";")


def test_prefetch_after_a_write_does_not_run_it_again(widgets):
    statement = Widget.query.sql(
        """
        INSERT INTO {Widget} ({Widget.name:name}, {Widget.size:name})
        VALUES ({name}, {size})
        RETURNING {Widget.*}
        """,
        name="once",
        size="small",
    )
    assert statement.execute() == 1
    assert statement.prefetch("tags").all()[0].name == "once"
    assert Widget.query.filter(name="once").count() == 1


def test_a_ciphertext_column_is_refused_on_every_execution(db):
    """A NULL first row, or a plan built by another statement, is no excuse."""
    SecretStore.query.create(name="null-one", api_key="k")

    @dataclass
    class Row:
        v: str | None

    # A statement with the same column signature (`v`, text, no source) runs
    # first and builds the plan.
    Widget.query.sql("SELECT {value}::text AS v", value="plain", result_type=Row).all()

    leaky = SecretStore.query.sql(
        "SELECT coalesce({SecretStore.api_key}, '') AS v FROM {SecretStore}",
        result_type=Row,
    )
    with pytest.raises(TypeError, match="nothing can decrypt it"):
        leaky.all()


def test_a_ciphertext_column_is_caught_past_the_first_row(db):
    SecretStore.query.create(name="a", api_key="k1", notes="")
    SecretStore.query.create(name="b", api_key="k2", notes="")

    @dataclass
    class Row:
        v: str | None

    statement = SecretStore.query.sql(
        """
        SELECT CASE WHEN {SecretStore.name} = {first} THEN NULL
                    ELSE {SecretStore.api_key} END AS v
        FROM {SecretStore}
        ORDER BY {SecretStore.name}
        """,
        first="a",
        result_type=Row,
    )
    with pytest.raises(TypeError, match="nothing can decrypt it"):
        statement.all()


def test_a_model_with_a_default_scope_can_still_write_sql(widgets, monkeypatch):
    """A default-filtering queryset is the starting point, not a narrowing.

    The scope is *not* applied to the statement — that's the whole point of
    writing it — so the statement states its own predicate.
    """
    from plain import postgres

    class SmallOnlyQuerySet(postgres.QuerySet):
        def __get__(self, instance, owner):
            return super().__get__(instance, owner).filter(size="small")

    monkeypatch.setattr(Widget, "query", SmallOnlyQuerySet())
    assert Widget.query.count() == 1  # the scope is live

    statement = Widget.query.sql("SELECT {Widget.*} FROM {Widget}")
    assert len(statement.all()) == 2  # and not applied to written SQL

    with pytest.raises(TypeError, match="order_by"):
        Widget.query.order_by("name").sql("SELECT {Widget.*} FROM {Widget}")
