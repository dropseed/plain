"""`Model.query.sql()` — written queries.

The contract: what an interpolation renders as, what a row comes back as, and
what a statement refuses. The static half — that the template has to be a
t-string and nothing else — lives in tests/typing/written_sql.py.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from string.templatelib import Template

import psycopg
import pytest
from app.examples.models.encrypted import SecretStore
from app.examples.models.mixins import MixinTestModel
from app.examples.models.relationships import Tag, Widget, WidgetTag
from app.examples.models.returning import ReturningEvent
from plain.exceptions import ValidationError


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
        t"SELECT count(*) AS n FROM {Widget}", result_type=SizeCount
    )
    assert f'"{Widget.model_options.db_table}"' in statement.sql


def test_field_reference_renders_the_qualified_column(widgets):
    statement = Widget.query.sql(
        t"""
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
    name = "fresh"
    size = "tiny"
    statement = Widget.query.sql(
        t"""
        INSERT INTO {Widget} ({Widget.name:name}, {Widget.size:name})
        VALUES ({name}, {size})
        RETURNING {Widget:*}
        """
    )
    assert '("name", "size")' in statement.sql
    assert statement.get().name == "fresh"


def test_foreign_key_reference_renders_the_id_column(widgets):
    """A foreign key is a descriptor at class level; its column is the `_id`."""
    small, _ = widgets
    table = WidgetTag.model_options.db_table

    @dataclass
    class TagCount:
        widget_id: int
        n: int

    widget_id = small.id
    statement = WidgetTag.query.sql(
        t"""
        SELECT {WidgetTag.widget} AS widget_id, count(*) AS n
        FROM {WidgetTag}
        WHERE {WidgetTag.widget} = {widget_id}
        GROUP BY 1
        """,
        result_type=TagCount,
    )
    assert f'"{table}"."widget_id"' in statement.sql
    assert statement.get() == TagCount(widget_id=small.id, n=2)


def test_star_reference_returns_model_instances(widgets):
    size = "small"
    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {size}"
    )
    widget = statement.get()
    assert isinstance(widget, Widget)
    assert widget.name == "small-widget"
    assert widget._state.adding is False


def test_value_binds_as_a_parameter(widgets):
    name = "small-widget"
    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.name} = {name}"
    )
    assert "%s" in statement.sql
    assert statement.params == ("small-widget",)
    assert statement.get().name == "small-widget"


def test_a_value_used_twice_binds_twice(widgets):
    name = "small"
    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*} FROM {Widget}
        WHERE {Widget.name} = {name} OR {Widget.size} = {name}
        """
    )
    assert statement.params == ("small", "small")
    assert statement.get().name == "small-widget"


def test_list_binds_as_an_array_for_any(widgets):
    names = ["small-widget", "large-widget"]
    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.name} = ANY({names}) ORDER BY 1"
    )
    assert len(statement.all()) == 2


def test_dict_binds_as_jsonb(db):
    ReturningEvent.query.create(label="signup", count=1, payload={"plan": "pro"})
    ReturningEvent.query.create(label="churn", count=1, payload={"plan": "free"})

    match = {"plan": "pro"}
    statement = ReturningEvent.query.sql(
        t"""
        SELECT {ReturningEvent:*} FROM {ReturningEvent}
        WHERE {ReturningEvent.payload} @> {match}
        """
    )
    event = statement.get()
    assert event.label == "signup"
    assert event.payload == {"plan": "pro"}


def test_a_nested_template_renders_inline(widgets):
    """A shared predicate is a t-string, interpolated into the statement."""
    small_only = t"{Widget.size} = 'small'"
    statement = Widget.query.sql(t"SELECT {Widget:*} FROM {Widget} WHERE {small_only}")
    assert "= 'small'" in statement.sql
    assert statement.get().name == "small-widget"


def test_a_nested_template_merges_its_parameters(widgets):
    """The nested template's own values bind, in the order they appear."""
    size = "small"
    named = "small-widget"
    predicate = t"{Widget.size} = {size}"
    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*} FROM {Widget}
        WHERE {predicate} AND {Widget.name} = {named}
        """
    )
    assert statement.params == ("small", "small-widget")
    assert statement.get().name == "small-widget"


def test_a_nested_template_nests_again(widgets):
    size = "small"
    innermost = t"{Widget.size} = {size}"
    middle = t"({innermost})"
    statement = Widget.query.sql(t"SELECT {Widget:*} FROM {Widget} WHERE {middle}")
    assert statement.params == ("small",)
    assert statement.get().name == "small-widget"


def test_embedded_queryset_becomes_a_subquery(widgets):
    small_widgets = Widget.query.where(Widget.size.equals("small"))

    statement = Widget.query.sql(
        t'SELECT sub."name" AS name FROM {small_widgets} sub ORDER BY 1',
        result_type=NameRow,
    )
    assert statement.all() == [NameRow(name="small-widget")]
    assert statement.params == ("small",)


def test_embedded_queryset_with_no_rows_still_renders(widgets):
    nothing = Widget.query.where(Widget.name.is_in([]))

    statement = Widget.query.sql(
        t'SELECT sub."name" AS name FROM {nothing} sub',
        result_type=NameRow,
    )
    assert statement.all() == []


def test_written_embeds_in_another_written(widgets):
    size = "small"
    inner = Widget.query.sql(
        t"SELECT {Widget.name} AS name FROM {Widget} WHERE {Widget.size} = {size}",
        result_type=NameRow,
    )
    outer = Widget.query.sql(
        t"SELECT sub.name AS name FROM {inner} sub",
        result_type=NameRow,
    )
    assert outer.params == ("small",)
    assert outer.all() == [NameRow(name="small-widget")]


def test_an_embedded_statement_ending_in_a_comment_survives(widgets):
    """The embed is put on its own lines, so a `-- comment` can't eat the `)`."""
    size = "small"
    inner = Widget.query.sql(
        t"""
        SELECT {Widget.name} AS name FROM {Widget} WHERE {Widget.size} = {size}
        -- the small ones
        """,
        result_type=NameRow,
    )
    outer = Widget.query.sql(
        t"SELECT sub.name AS name FROM {inner} sub",
        result_type=NameRow,
    )
    assert outer.all() == [NameRow(name="small-widget")]


def test_a_literal_percent_survives_and_stays_readable(widgets):
    pattern = "small"
    statement = Widget.query.sql(
        t"""
        SELECT {Widget.name} AS name FROM {Widget}
        WHERE {Widget.name} LIKE {pattern} || '%'
        """,
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
    statement = SecretStore.query.sql(t"SELECT {SecretStore:*} FROM {SecretStore}")
    secret = statement.get()
    assert secret.api_key == "sk-live-123"
    assert secret.notes == "top secret"
    assert secret.config == {"a": 1}


def test_a_model_field_is_filled_from_the_star_expansion(widgets):
    """A statement that selects more than `{Model:*}` declares its own shape."""

    @dataclass
    class WidgetRow:
        widget: Widget
        tag_count: int

    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*}, count(wt.id) AS tag_count
        FROM {Widget}
        LEFT JOIN {WidgetTag} wt ON wt.widget_id = {Widget.id}
        GROUP BY {Widget.id}
        ORDER BY {Widget.name}
        """,
        result_type=WidgetRow,
    )
    rows = statement.all()
    assert [(row.widget.name, row.tag_count) for row in rows] == [
        ("large-widget", 1),
        ("small-widget", 2),
    ]
    assert isinstance(rows[0].widget, Widget)
    assert rows[0].widget._state.adding is False


def test_a_model_field_decrypts_and_parses_like_an_instance_row(db):
    """The expansion hydrates exactly as an instance statement's row does."""
    SecretStore.query.create(
        name="prod", api_key="sk-live-123", notes="top secret", config={"a": 1}
    )

    @dataclass
    class SecretRow:
        secret: SecretStore
        shouted: str

    statement = SecretStore.query.sql(
        t"""
        SELECT {SecretStore:*}, upper({SecretStore.name}) AS shouted
        FROM {SecretStore}
        """,
        result_type=SecretRow,
    )
    row = statement.get()
    assert row.secret.api_key == "sk-live-123"
    assert row.secret.config == {"a": 1}
    assert row.shouted == "PROD"


def test_a_repeated_column_is_its_own_field(widgets):
    """`{Widget:*}` and an expression over one of its columns: both arrive."""

    @dataclass
    class DisplayRow:
        widget: Widget
        display_name: str

    size = "small"
    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*}, upper({Widget.name}) AS display_name
        FROM {Widget}
        WHERE {Widget.size} = {size}
        """,
        result_type=DisplayRow,
    )
    row = statement.get()
    assert row.widget.name == "small-widget"
    assert row.display_name == "SMALL-WIDGET"


def test_a_self_join_hydrates_the_row_it_selected(widgets):
    """The instance is `{Widget:*}`'s columns, not whatever traces to Widget.

    Both sides of a self-join trace back to the same table, so picking the
    expansion's columns by provenance would mix the two rows together.
    """
    Widget.query.create(name="other-small", size="small")
    small = Widget.query.get(name="small-widget")

    @dataclass
    class Neighbour:
        widget: Widget
        other_name: str

    name = "small-widget"
    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*}, other."name" AS other_name
        FROM {Widget}
        JOIN {Widget} other
          ON other."size" = {Widget.size} AND other."id" <> {Widget.id}
        WHERE {Widget.name} = {name}
        """,
        result_type=Neighbour,
    )
    row = statement.get()
    assert row.widget.id == small.id
    assert row.widget.name == "small-widget"
    assert row.other_name == "other-small"


def test_two_models_fill_two_fields(widgets):
    """One expansion each, matched to the field annotated with that model."""

    @dataclass
    class Tagged:
        widget: Widget
        tag: Tag

    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*}, {Tag:*}
        FROM {Widget}
        JOIN {WidgetTag} wt ON wt.widget_id = {Widget.id}
        JOIN {Tag} ON {Tag.id} = wt.tag_id
        ORDER BY {Widget.name}, {Tag.name}
        """,
        result_type=Tagged,
    )
    assert [(row.widget.name, row.tag.name) for row in statement] == [
        ("large-widget", "red"),
        ("small-widget", "blue"),
        ("small-widget", "red"),
    ]


def test_an_outer_join_that_matched_nothing_is_none(widgets):
    """`Tag | None` is what the outer side of a LEFT JOIN needs."""
    Widget.query.create(name="bare-widget", size="tiny")

    @dataclass
    class MaybeTagged:
        widget: Widget
        tag: Tag | None

    names = ["bare-widget", "large-widget"]
    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*}, {Tag:*}
        FROM {Widget}
        LEFT JOIN {WidgetTag} wt ON wt.widget_id = {Widget.id}
        LEFT JOIN {Tag} ON {Tag.id} = wt.tag_id
        WHERE {Widget.name} = ANY({names})
        ORDER BY {Widget.name}
        """,
        result_type=MaybeTagged,
    )
    rows = statement.all()
    assert [row.widget.name for row in rows] == ["bare-widget", "large-widget"]
    assert rows[0].tag is None
    assert rows[1].tag is not None
    assert rows[1].tag.name == "red"


def test_star_columns_work_through_a_union(widgets):
    """A UNION drops every column's source; the expansion still says what a row is."""
    small = "small"
    large = "large"
    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {small}
        UNION ALL
        SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {large}
        """
    )
    names = sorted(widget.name for widget in statement)
    assert names == ["large-widget", "small-widget"]
    assert all(isinstance(widget, Widget) for widget in statement)


def test_extra_columns_without_a_result_type_are_refused(widgets):
    """An instance is complete and carries only its columns; nothing is attached."""
    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*}, count(wt.id) AS tag_count
        FROM {Widget}
        LEFT JOIN {WidgetTag} wt ON wt.widget_id = {Widget.id}
        GROUP BY {Widget.id}
        """,
    )
    with pytest.raises(TypeError, match="shape of its own"):
        statement.all()


def test_a_model_field_with_no_expansion_is_refused(widgets):
    @dataclass
    class WidgetRow:
        widget: Widget

    statement = Widget.query.sql(
        t"SELECT {Widget.name} AS name FROM {Widget}", result_type=WidgetRow
    )
    with pytest.raises(TypeError, match=r"nothing in this statement selects"):
        statement.all()


def test_an_expansion_with_no_model_field_is_refused(widgets):
    """In the outer select list there is nothing else a `{Model:*}` could be."""
    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget}", result_type=NameRow
    )
    with pytest.raises(TypeError, match="no Widget field to put it in"):
        statement.all()


def test_a_non_nullable_model_field_that_came_back_null_is_refused(widgets):
    Widget.query.create(name="bare-widget", size="tiny")

    @dataclass
    class Tagged:
        widget: Widget
        tag: Tag

    name = "bare-widget"
    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*}, {Tag:*}
        FROM {Widget}
        LEFT JOIN {WidgetTag} wt ON wt.widget_id = {Widget.id}
        LEFT JOIN {Tag} ON {Tag.id} = wt.tag_id
        WHERE {Widget.name} = {name}
        """,
        result_type=Tagged,
    )
    with pytest.raises(TypeError, match=r"Annotate it `Tag \| None`"):
        statement.all()


def test_the_same_model_expanded_twice_is_refused(widgets):
    """Which expansion fills the field is the question a self-join can't answer."""

    @dataclass
    class Ranked:
        widget: Widget
        rank: int

    size = "small"
    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*}, 1 AS rank FROM {Widget} WHERE {Widget.size} = {size}
        UNION ALL
        SELECT {Widget:*}, 2 AS rank FROM {Widget}
        """,
        result_type=Ranked,
    )
    with pytest.raises(TypeError, match=r"expands \{Widget:\*\} 2 times"):
        statement.all()


def test_two_fields_of_one_model_are_refused(widgets):
    @dataclass
    class Pair:
        widget: Widget
        other: Widget

    statement = Widget.query.sql(t"SELECT {Widget:*} FROM {Widget}", result_type=Pair)
    with pytest.raises(TypeError, match="more than one Widget field"):
        statement.all()


def test_prefetch_is_refused_on_a_result_type_statement(widgets):
    """`prefetch()` attaches to instances; a declared row is not one."""

    @dataclass
    class WidgetRow:
        widget: Widget
        tag_count: int

    with pytest.raises(TypeError, match="returns rows"):
        Widget.query.sql(
            t"""
            SELECT {Widget:*}, count(wt.id) AS tag_count
            FROM {Widget}
            LEFT JOIN {WidgetTag} wt ON wt.widget_id = {Widget.id}
            GROUP BY {Widget.id}
            """,
            result_type=WidgetRow,
        ).prefetch("tags")


def test_result_type_maps_columns_by_name(widgets):
    statement = Widget.query.sql(
        t"""
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
        t"""
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
        t"""
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

    value = 1
    statement = ReturningEvent.query.sql(
        t"SELECT jsonb_build_object('a', {value}::int) AS payload",
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
        t"SELECT {Widget.name} AS name FROM {Widget} ORDER BY 1",
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
        t"SELECT coalesce({SecretStore.api_key}, '') AS api_key FROM {SecretStore}",
        result_type=SecretRow,
    )
    with pytest.raises(TypeError, match="nothing can decrypt it"):
        statement.all()


def test_prefetch_loads_related_objects(widgets, capture_queries, executed_sql):
    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} ORDER BY {Widget.name}"
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
        t"SELECT {Widget:*} FROM {Widget} ORDER BY {Widget.name}",
    )
    assert statement.count() == 2
    assert statement.exists() is True
    first = statement.first()
    assert first is not None
    assert first.name == "large-widget"

    size = "small"
    one = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {size}"
    )
    assert one.get().name == "small-widget"


def test_get_raises_the_models_exceptions(widgets):
    size = "nope"
    none = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {size}"
    )
    with pytest.raises(Widget.DoesNotExist):
        none.get()

    both = Widget.query.sql(t"SELECT {Widget:*} FROM {Widget}")
    with pytest.raises(Widget.MultipleObjectsReturned):
        both.get()


def test_get_on_a_row_statement_raises_value_error(widgets):
    statement = Widget.query.sql(
        t"SELECT {Widget.size} AS size, count(*) AS n FROM {Widget} GROUP BY 1",
        result_type=SizeCount,
    )
    with pytest.raises(ValueError, match="2 rows"):
        statement.get()


def test_exists_is_false_on_no_rows(widgets):
    size = "nope"
    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {size}"
    )
    assert statement.exists() is False
    assert statement.count() == 0
    assert statement.first() is None
    assert list(statement) == []


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def test_write_with_returning_gives_instances(widgets):
    size = "medium"
    name = "small-widget"
    statement = Widget.query.sql(
        t"""
        UPDATE {Widget} SET {Widget.size:name} = {size}
        WHERE {Widget.name} = {name}
        RETURNING {Widget:*}
        """
    )
    updated = statement.get()
    assert isinstance(updated, Widget)
    assert updated.size == "medium"
    assert Widget.query.get(name="small-widget").size == "medium"


def test_write_without_returning_gives_a_row_count(widgets):
    size = "tiny"
    old = "small"
    statement = Widget.query.sql(
        t"""
        UPDATE {Widget} SET {Widget.size:name} = {size}
        WHERE {Widget.size} = {old}
        """
    )
    assert statement.execute() == 1
    assert list(statement) == []
    assert Widget.query.filter(size="tiny").count() == 1


def test_asking_a_resultless_write_about_rows_is_refused(widgets):
    """0 would read like "the UPDATE matched nothing"."""
    size = "tiny"
    statement = Widget.query.sql(t"UPDATE {Widget} SET {Widget.size:name} = {size}")
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
    size = "small"
    statement = Widget.query.sql(
        t"DELETE FROM {Widget} WHERE {Widget.size} = {size} RETURNING {Widget.id}"
    )
    assert statement.execute() == 1
    assert statement.count() == 1
    assert Widget.query.filter(size="small").count() == 0


def test_a_write_runs_once_however_it_is_asked(widgets):
    """count()/first()/get() never run a write a second time."""
    name = "once"
    size = "small"
    statement = Widget.query.sql(
        t"""
        INSERT INTO {Widget} ({Widget.name:name}, {Widget.size:name})
        VALUES ({name}, {size})
        RETURNING {Widget:*}
        """
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

    name = "fresh"
    size = "small"
    statement = Widget.query.sql(
        t"""
        INSERT INTO {Widget} ({Widget.name:name}, {Widget.size:name})
        VALUES ({name}, {size})
        RETURNING {Widget.id} AS id, {Widget.name} AS name
        """,
        result_type=NewWidget,
    )
    row = statement.get()
    assert row.name == "fresh"
    assert Widget.query.get(id=row.id).name == "fresh"


def test_unique_violation_maps_to_validation_error(widgets):
    """Any model's constraint maps, not just the queryset's own."""
    name = "red"  # unique_tag_name already holds "red"
    statement = Widget.query.sql(t"INSERT INTO {Tag} ({Tag.name:name}) VALUES ({name})")
    with pytest.raises(ValidationError):
        statement.execute()


def test_foreign_key_violation_maps_to_validation_error(widgets):
    small, _ = widgets
    widget_id = small.id
    tag_id = 999_999
    statement = WidgetTag.query.sql(
        t"""
        INSERT INTO {WidgetTag} ({WidgetTag.widget:name}, {WidgetTag.tag:name})
        VALUES ({widget_id}, {tag_id})
        """
    )
    with pytest.raises(ValidationError):
        statement.execute()


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_string_is_not_a_template(db):
    """The static half is in tests/typing/written_sql.py."""
    statement = "SELECT {Widget:*} FROM {Widget}"
    with pytest.raises(TypeError, match="takes a t-string"):
        Widget.query.sql(statement)  # ty: ignore[invalid-argument-type]


def test_a_hand_built_template_is_the_deliberate_escape_hatch(db):
    """What the type actually guarantees, stated honestly.

    `sql()` refuses a `str`, so no string reaches it by accident. Building a
    `Template` out of one yourself is the way past that, and it runs — which
    is why the rule is "never build one from anything outside the program",
    not "injection is impossible".
    """

    @dataclass
    class Row:
        n: int

    built = Template("SELECT 1 AS n")
    assert Widget.query.sql(built, result_type=Row).get() == Row(n=1)


def test_values_are_not_passed_by_keyword(db):
    """A t-string already carries its values; there is no `**values`."""
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        Widget.query.sql(  # ty: ignore[no-matching-overload]
            t"SELECT {Widget:*} FROM {Widget}", size="small"
        )


def test_a_conversion_is_refused(db):
    size = "small"
    with pytest.raises(ValueError, match="uses a conversion"):
        Widget.query.sql(
            t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {size!r}"
        )


def test_a_bad_format_spec_on_a_column_quotes_what_was_written(db):
    with pytest.raises(ValueError, match=r"\{Widget\.size:bare\}"):
        Widget.query.sql(t"SELECT {Widget.size:bare} FROM {Widget}")


def test_a_bad_format_spec_on_a_model_quotes_what_was_written(db):
    with pytest.raises(ValueError, match=r"\{Widget:all\}"):
        Widget.query.sql(t"SELECT {Widget:all} FROM {Widget}")


def test_a_format_spec_on_a_value_is_refused(db):
    size = "small"
    with pytest.raises(ValueError, match="a value takes no format spec"):
        Widget.query.sql(
            t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {size:>10}"
        )


def test_a_format_spec_on_a_nested_template_is_refused(db):
    predicate = t"{Widget.size} = 'small'"
    with pytest.raises(ValueError, match="nested template takes no format spec"):
        Widget.query.sql(t"SELECT {Widget:*} FROM {Widget} WHERE {predicate:x}")


# ---------------------------------------------------------------------------
# Braces that were meant to be braces
# ---------------------------------------------------------------------------


def test_an_undoubled_regex_quantifier_is_refused(db):
    """`{2}` is a quantifier the braces weren't doubled in, not a parameter."""
    with pytest.raises(ValueError, match="interpolates the number 2"):
        Widget.query.sql(t"SELECT {Widget:*} FROM {Widget} WHERE name ~ '^a{2}$'")


def test_a_doubled_regex_quantifier_renders_the_brace(widgets):
    Widget.query.create(name="aa", size="small")
    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.name} ~ '^a{{2}}$'"
    )
    assert "'^a{2}$'" in statement.sql
    assert statement.get().name == "aa"


def test_an_undoubled_regex_range_is_refused(db):
    """`{2,5}` reaches the renderer as a tuple of two ints."""
    with pytest.raises(ValueError, match="interpolates a tuple"):
        Widget.query.sql(t"SELECT {Widget:*} FROM {Widget} WHERE name ~ '^a{2, 5}$'")


def test_an_undoubled_array_literal_is_refused(db):
    with pytest.raises(ValueError, match="interpolates a tuple"):
        Widget.query.sql(t"SELECT '{1, 2, 3}'::int[] AS ids")


def test_a_doubled_array_literal_renders(db):
    @dataclass
    class Ids:
        ids: list

    statement = Widget.query.sql(t"SELECT '{{1,2,3}}'::int[] AS ids", result_type=Ids)
    assert statement.get() == Ids(ids=[1, 2, 3])


def test_an_undoubled_jsonb_literal_is_refused(db):
    """`{"a": 1}` splits into the expression `"a"` and a junk format spec.

    So it lands on the format-spec refusal rather than the brace lookalike,
    and that message carries the doubling hint too.
    """
    with pytest.raises(ValueError, match="double it"):
        Widget.query.sql(t"""SELECT '{"a": 1}'::jsonb AS payload""")


def test_a_doubled_jsonb_literal_renders(db):
    @dataclass
    class Payload:
        payload: dict

    statement = Widget.query.sql(
        t"""SELECT '{{"a": 1}}'::jsonb AS payload""", result_type=Payload
    )
    assert statement.get() == Payload(payload={"a": 1})


def test_none_binds_as_null(db):
    """`{None}` is a value, not a brace lookalike — it sets a column NULL."""
    ReturningEvent.query.create(label="signup", count=1, payload={"plan": "pro"})

    statement = ReturningEvent.query.sql(
        t"""
        UPDATE {ReturningEvent} SET {ReturningEvent.payload:name} = {None}
        RETURNING {ReturningEvent:*}
        """
    )
    assert statement.params == (None,)
    assert statement.get().payload is None


def test_a_string_literal_binds(widgets):
    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {'small'}"
    )
    assert statement.params == ("small",)
    assert statement.get().name == "small-widget"


def test_a_boolean_literal_binds(db):
    @dataclass
    class Flag:
        flag: bool

    statement = Widget.query.sql(t"SELECT {True}::boolean AS flag", result_type=Flag)
    assert statement.params == (True,)
    assert statement.get() == Flag(flag=True)


# ---------------------------------------------------------------------------
# Things that look like columns and aren't
# ---------------------------------------------------------------------------


def test_a_traversal_is_not_a_column(db):
    """`where()` follows a relation by building a join; a written query can't."""
    with pytest.raises(ValueError, match="is a traversal"):
        WidgetTag.query.sql(t"SELECT {WidgetTag.widget.name} FROM {WidgetTag}")


def test_a_model_instance_is_not_a_value(widgets):
    """`{job}` where `{job.id}` was meant, caught before it reaches psycopg."""
    small, _ = widgets
    with pytest.raises(TypeError, match="instance, not something"):
        Widget.query.sql(t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.id} = {small}")


def test_a_many_to_many_accessor_is_not_a_column(db):
    with pytest.raises(TypeError, match="is a relation"):
        Widget.query.sql(t"SELECT {Widget.tags} FROM {Widget}")


def test_a_reverse_accessor_is_not_a_column(db):
    with pytest.raises(TypeError, match="is a relation"):
        Tag.query.sql(t"SELECT {Tag.widgets} FROM {Tag}")


def test_a_trailing_semicolon_is_dropped(widgets):
    size = "small"
    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {size};"
    )
    assert statement.get().name == "small-widget"


def test_a_second_statement_is_refused_when_a_parameter_binds(widgets):
    """With a parameter the statement goes over the extended protocol."""
    size = "small"
    statement = Widget.query.sql(
        t"""
        SELECT {Widget.id} FROM {Widget} WHERE {Widget.size} = {size};
        DELETE FROM {Widget}
        """
    )
    with pytest.raises(psycopg.errors.SyntaxError, match="multiple commands"):
        statement.execute()


def test_a_second_statement_is_refused_without_parameters(widgets):
    """With nothing to bind psycopg sends a simple query, which would run both."""
    with pytest.raises(ValueError, match="single statement"):
        Widget.query.sql(t"SELECT 1 AS n; DELETE FROM {Widget}")
    assert Widget.query.count() == 2


def test_sql_needs_a_bare_queryset(db):
    with pytest.raises(TypeError, match="where\\(\\)/filter\\(\\)"):
        Widget.query.where(Widget.size.equals("small")).sql(
            t"SELECT {Widget:*} FROM {Widget}"
        )
    with pytest.raises(TypeError, match="order_by"):
        Widget.query.order_by("name").sql(t"SELECT {Widget:*} FROM {Widget}")
    with pytest.raises(TypeError, match="slicing"):
        Widget.query.all()[:2].sql(t"SELECT {Widget:*} FROM {Widget}")


def test_result_type_must_be_a_dataclass(db):
    with pytest.raises(TypeError, match="requires a dataclass"):
        Widget.query.sql(  # ty: ignore[no-matching-overload]
            t"SELECT 1 AS n FROM {Widget}", result_type=int
        )


def test_a_star_inside_a_subquery_is_just_columns(widgets):
    """`result_type=` says what a row is; a `{Model:*}` below it is columns."""
    statement = Widget.query.sql(
        t"""
        SELECT count(*) AS n, {Widget.size} AS size
        FROM (SELECT {Widget:*} FROM {Widget}) AS {Widget}
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
        t"SELECT count(*) AS n FROM (SELECT {Widget:*} FROM {Widget}) sub"
    )
    with pytest.raises(TypeError, match="inside a subquery"):
        statement.all()


def test_two_models_starred_are_refused(db):
    with pytest.raises(TypeError, match="more than one model"):
        Widget.query.sql(
            t"SELECT {Widget:*}, {Tag:*} FROM {Widget}, {Tag}",
        )


def test_rows_with_no_result_type_are_refused(widgets):
    statement = Widget.query.sql(t"SELECT {Widget.size} AS size FROM {Widget}")
    with pytest.raises(TypeError, match="result_type"):
        statement.all()


def test_result_type_column_mismatch(widgets):
    @dataclass
    class Wrong:
        size: str
        missing: int

    statement = Widget.query.sql(
        t"SELECT {Widget.size} AS size FROM {Widget}", result_type=Wrong
    )
    with pytest.raises(TypeError, match="no column for missing"):
        statement.all()


def test_result_type_type_mismatch(widgets):
    @dataclass
    class Wrong:
        size: Decimal
        n: int

    statement = Widget.query.sql(
        t"SELECT {Widget.size} AS size, count(*) AS n FROM {Widget} GROUP BY 1",
        result_type=Wrong,
    )
    with pytest.raises(TypeError, match="comes back as str"):
        statement.all()


def test_the_plan_follows_the_columns_not_the_template(widgets):
    """The same statement with a different subquery is a different statement."""
    by_name = Widget.query.values("name")
    names = Widget.query.sql(
        t'SELECT sub."name" AS name FROM {by_name} sub ORDER BY 1',
        result_type=NameRow,
    )
    assert names.all() == [NameRow(name="large-widget"), NameRow(name="small-widget")]

    by_size = Widget.query.values("size")
    sizes = Widget.query.sql(
        t'SELECT sub."name" AS name FROM {by_size} sub ORDER BY 1',
        result_type=NameRow,
    )
    with pytest.raises(psycopg.errors.UndefinedColumn):
        sizes.all()


def test_a_trailing_comment_survives_the_row_limit(widgets):
    """first()/get()/count() wrap the statement; a `-- comment` can't swallow it."""
    statement = Widget.query.sql(
        t"""
        SELECT {Widget:*} FROM {Widget} ORDER BY {Widget.name}
        -- the oldest one
        """
    )
    first = statement.first()
    assert first is not None
    assert first.name == "large-widget"
    assert statement.count() == 2


def test_a_trailing_semicolon_is_dropped_from_the_sql_too(widgets):
    size = "small"
    statement = Widget.query.sql(
        t"SELECT {Widget:*} FROM {Widget} WHERE {Widget.size} = {size};  "
    )
    assert not statement.sql.rstrip().endswith(";")


def test_prefetch_after_a_write_does_not_run_it_again(widgets):
    name = "once"
    size = "small"
    statement = Widget.query.sql(
        t"""
        INSERT INTO {Widget} ({Widget.name:name}, {Widget.size:name})
        VALUES ({name}, {size})
        RETURNING {Widget:*}
        """
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
    value = "plain"
    Widget.query.sql(t"SELECT {value}::text AS v", result_type=Row).all()

    leaky = SecretStore.query.sql(
        t"SELECT coalesce({SecretStore.api_key}, '') AS v FROM {SecretStore}",
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

    first = "a"
    statement = SecretStore.query.sql(
        t"""
        SELECT CASE WHEN {SecretStore.name} = {first} THEN NULL
                    ELSE {SecretStore.api_key} END AS v
        FROM {SecretStore}
        ORDER BY {SecretStore.name}
        """,
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

    statement = Widget.query.sql(t"SELECT {Widget:*} FROM {Widget}")
    assert len(statement.all()) == 2  # and not applied to written SQL

    with pytest.raises(TypeError, match="order_by"):
        Widget.query.order_by("name").sql(t"SELECT {Widget:*} FROM {Widget}")
