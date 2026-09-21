"""Runtime behavior of `QuerySet.select()` — typed column selection that
returns honest rows (tuples, scalars, or dataclasses), never partial model
instances.

The static-typing contract lives in tests/typing/select_rows.py.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field, fields

import pytest
from app.examples.models.alias_collisions import AliasCollisionExample
from app.examples.models.defaults import DefaultsExample
from app.examples.models.delete import CircA, CircB, Grandchild
from app.examples.models.mixins import MixinTestModel, TimestampMixin
from app.examples.models.relationships import Tag, Widget, WidgetTag
from plain.postgres import RowQuerySet
from plain.postgres.aggregates import Count
from plain.postgres.expressions import F, Value
from plain.postgres.functions import Lower, Upper


@pytest.fixture
def rows(db):
    DefaultsExample.query.create(name="alpha", priority=3, note="first")
    DefaultsExample.query.create(name="beta", priority=1, note=None)
    DefaultsExample.query.create(name="gamma", priority=2, note="third")


def test_select_returns_tuple_rows(rows):
    result = (
        DefaultsExample.query.order_by("priority")
        .select(DefaultsExample.name, DefaultsExample.priority)
        .all()
    )
    assert list(result) == [("beta", 1), ("gamma", 2), ("alpha", 3)]


def test_select_flat_returns_scalars(rows):
    names = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name, flat=True)
        .all()
    )
    assert list(names) == ["alpha", "beta", "gamma"]


def test_select_single_column_is_one_tuple(rows):
    result = DefaultsExample.query.order_by("name").select(DefaultsExample.name)
    assert list(result) == [("alpha",), ("beta",), ("gamma",)]


def test_select_preserves_nullable_values(rows):
    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name, DefaultsExample.note)
        .all()
    )
    assert list(result) == [("alpha", "first"), ("beta", None), ("gamma", "third")]


def test_select_chains_with_where(rows):
    result = DefaultsExample.query.where(DefaultsExample.priority.gte(2)).select(
        DefaultsExample.name, flat=True
    )
    assert sorted(result) == ["alpha", "gamma"]


def test_select_expression_column(rows):
    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.priority, Upper("name"))
        .all()
    )
    assert list(result) == [(3, "ALPHA"), (1, "BETA"), (2, "GAMMA")]


def test_select_f_expression_column(rows):
    """F() is a Combinable, not a BaseExpression -- select() takes it anyway,
    because values_list() does. Static half: tests/typing/select_rows.py."""
    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name, F("priority"))
        .all()
    )
    assert list(result) == [("alpha", 3), ("beta", 1), ("gamma", 2)]


def test_select_combined_f_expression_column(rows):
    result = DefaultsExample.query.order_by("name").select(F("priority") + 1, flat=True)
    assert list(result) == [4, 2, 3]


def test_select_returns_row_queryset(rows):
    result = DefaultsExample.query.select(DefaultsExample.name)
    assert isinstance(result, RowQuerySet)


def test_select_first_returns_row(rows):
    row = (
        DefaultsExample.query.order_by("priority")
        .select(DefaultsExample.name, DefaultsExample.priority)
        .first()
    )
    assert row == ("beta", 1)


def test_select_get_returns_row(rows):
    row = (
        DefaultsExample.query.where(DefaultsExample.name.equals("alpha"))
        .select(DefaultsExample.name, DefaultsExample.priority)
        .get()
    )
    assert row == ("alpha", 3)


# ---- result_type=Dataclass ----


@dataclass
class NameStat:
    name: str
    priority: int


def test_select_result_type_builds_dataclass(rows):
    result = (
        DefaultsExample.query.order_by("priority")
        .select(DefaultsExample.name, DefaultsExample.priority, result_type=NameStat)
        .all()
    )
    assert list(result) == [
        NameStat(name="beta", priority=1),
        NameStat(name="gamma", priority=2),
        NameStat(name="alpha", priority=3),
    ]


def test_select_result_type_with_expression_column(rows):
    @dataclass
    class NameUpper:
        priority: int
        upper: str

    result = (
        DefaultsExample.query.order_by("name")
        .select(
            DefaultsExample.priority,
            Upper("name"),
            result_type=NameUpper,
        )
        .all()
    )
    assert result[0] == NameUpper(priority=3, upper="ALPHA")


# ---- error paths ----


def test_select_requires_at_least_one_column(db):
    with pytest.raises(TypeError, match="at least one column"):
        DefaultsExample.query.select()


def test_select_rejects_string_argument(db):
    with pytest.raises(TypeError, match="strings"):
        DefaultsExample.query.select("name")  # ty: ignore[no-matching-overload]


def test_select_rejects_fk_traversal(db):
    """The message names the values_list() spelling that does work."""
    with pytest.raises(TypeError, match=r'values_list\("widget__name"\)'):
        WidgetTag.query.select(WidgetTag.widget.name)


def test_select_rejects_fk_reference(db):
    """A relation is not a column, and the message names the one that is."""
    with pytest.raises(TypeError, match=r"key column instead -- WidgetTag\.widget\.id"):
        WidgetTag.query.select(WidgetTag.widget)  # ty: ignore[no-matching-overload]


def test_select_flat_rejects_more_than_one_column(db):
    """The message names select(), not the values_list() plumbing underneath."""
    with pytest.raises(TypeError, match=r"select\(flat=True\) takes exactly one"):
        DefaultsExample.query.select(  # ty: ignore[no-matching-overload]
            DefaultsExample.name, DefaultsExample.priority, flat=True
        )


class TestSelectForeignKeyColumn:
    """A foreign key's own key column is a local column, so it is selectable.

    `WidgetTag.widget.id` is `"widgettag"."widget_id"` — no join, and no
    nullability the type doesn't already carry. The SQL identity with
    `values_list("widget")` is pinned in
    tests/internal/test_select_fk_column_sql.py.
    """

    @pytest.fixture
    def tagged(self, db):
        widget = Widget.query.create(name="w", size="s")
        tag = Tag.query.create(name="t")
        return WidgetTag.query.create(widget=widget, tag=tag)

    def test_flat_selects_the_key_column(self, tagged):
        assert list(WidgetTag.query.select(WidgetTag.widget.id, flat=True)) == [
            tagged.widget.id
        ]

    def test_tuple_row_carries_the_key_column(self, tagged):
        assert list(WidgetTag.query.select(WidgetTag.widget.id, WidgetTag.tag.id)) == [
            (tagged.widget.id, tagged.tag.id)
        ]

    def test_result_type_maps_it_onto_the_column_name(self, tagged):
        @dataclass
        class TagRow:
            widget_id: int
            tag_id: int

        rows = list(
            WidgetTag.query.select(
                WidgetTag.widget.id, WidgetTag.tag.id, result_type=TagRow
            )
        )
        assert rows == [TagRow(widget_id=tagged.widget.id, tag_id=tagged.tag.id)]

    def test_result_type_name_must_be_the_column_name(self, tagged):
        """The dataclass field names the column the row holds, `widget_id` --
        not the relation, and not the `widget__id` lookup path."""

        @dataclass
        class WidgetRow:
            widget: int

        with pytest.raises(TypeError, match="'widget_id' does not match"):
            WidgetTag.query.select(WidgetTag.widget.id, result_type=WidgetRow)

    def test_nullable_key_column_comes_back_as_none(self, db):
        """A nullable foreign key yields None, which is the key column's own
        nullability — not something the join introduced."""
        partner = CircA.query.create(name="a")
        CircB.query.create(name="paired", partner=partner)
        CircB.query.create(name="lone")

        assert list(
            CircB.query.order_by("name").select(CircB.partner.id, flat=True)
        ) == [None, partner.id]

    def test_a_non_key_column_is_still_refused(self, db):
        """One hop, but the column lives on the related table."""
        with pytest.raises(TypeError, match=r'values_list\("widget__name"\)'):
            WidgetTag.query.select(WidgetTag.widget.name)

    def test_two_hops_to_a_key_column_are_still_refused(self, db):
        """The second hop's key column lives on the related table, not this
        one, so it really does arrive over a join."""
        with pytest.raises(
            TypeError, match=r'values_list\("mid_parent__grandparent__id"\)'
        ):
            Grandchild.query.select(Grandchild.mid_parent.grandparent.id)

    def test_many_to_many_hop_is_still_refused(self, db):
        """A many-to-many stores its keys in a third table, so its key column
        is never local to the selecting one."""
        with pytest.raises(TypeError, match=r'values_list\("widget__tags__id"\)'):
            # The checker stops a hop earlier: a many-to-many is a manager at
            # class level, with no fields hanging off it.
            WidgetTag.query.select(
                WidgetTag.widget.tags.id  # ty: ignore[unresolved-attribute]
            )


def test_select_result_type_must_be_dataclass(db):
    with pytest.raises(TypeError, match="dataclass"):
        DefaultsExample.query.select(DefaultsExample.name, result_type=dict)


def test_select_result_type_arity_must_match(db):
    with pytest.raises(TypeError, match="constructor arguments"):
        DefaultsExample.query.select(DefaultsExample.name, result_type=NameStat)


def test_select_result_type_field_name_must_match(db):
    @dataclass
    class Renamed:
        label: str
        priority: int

    with pytest.raises(TypeError, match="positionally"):
        DefaultsExample.query.select(
            DefaultsExample.name, DefaultsExample.priority, result_type=Renamed
        )


def test_select_flat_and_result_type_conflict(db):
    with pytest.raises(TypeError, match="combine flat"):
        DefaultsExample.query.select(  # ty: ignore[no-matching-overload]
            DefaultsExample.name, flat=True, result_type=NameStat
        )


def test_select_result_type_ignores_init_false_fields(rows):
    """An init=False field is computed by the dataclass, so it is neither
    selected nor counted against the arity."""

    @dataclass
    class Computed:
        name: str
        priority: int
        label: str = field(default="", init=False)

        def __post_init__(self) -> None:
            self.label = f"{self.name}:{self.priority}"

    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name, DefaultsExample.priority, result_type=Computed)
        .first()
    )
    assert result == Computed(name="alpha", priority=3)
    assert result.label == "alpha:3"


def test_select_result_type_counts_init_vars(rows):
    """An InitVar is a constructor parameter that never appears in
    dataclasses.fields(), so the columns are mapped off the signature."""

    @dataclass
    class WithInitVar:
        name: str
        priority: InitVar[int]

        def __post_init__(self, priority: int) -> None:
            # `priority` is a constructor argument only -- consumed here and
            # never stored, which is why fields() doesn't list it.
            assert priority > 0

    assert [f.name for f in fields(WithInitVar)] == ["name"]

    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name, DefaultsExample.priority, result_type=WithInitVar)
        .first()
    )
    assert result == WithInitVar(name="alpha", priority=3)


def test_select_result_type_handles_init_var_and_init_false_together(rows):
    """fields() disagrees with the constructor in both directions here: it
    lists `computed` (which can't be passed) and omits `priority` (which
    must be). The signature is right on both counts."""

    @dataclass
    class Mixed:
        name: str
        priority: InitVar[int]
        computed: str = field(default="", init=False)

        def __post_init__(self, priority: int) -> None:
            self.computed = f"{self.name}/{priority}"

    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name, DefaultsExample.priority, result_type=Mixed)
        .first()
    )
    assert result == Mixed(name="alpha", priority=3)
    assert result.computed == "alpha/3"


def test_select_result_type_arity_counts_init_vars(rows):
    @dataclass
    class OnlyInitVar:
        name: str
        priority: InitVar[int]

        def __post_init__(self, priority: int) -> None:
            pass

    with pytest.raises(TypeError, match="takes 2 constructor arguments but 1"):
        DefaultsExample.query.select(DefaultsExample.name, result_type=OnlyInitVar)


class TestResultTypeParameterKinds:
    """Parameter kind decides how each value has to be passed. A signature
    always orders positionals before keyword-onlys, so the row splits at one
    point -- but the split has to happen, because a positional-only parameter
    can't be filled by name and a keyword-only one can't be filled by
    position."""

    def test_all_positional(self, rows):
        @dataclass
        class AllPositional:
            name: str
            priority: int

        result = (
            DefaultsExample.query.order_by("name")
            .select(
                DefaultsExample.name,
                DefaultsExample.priority,
                result_type=AllPositional,
            )
            .first()
        )
        assert result == AllPositional(name="alpha", priority=3)

    def test_all_keyword_only(self, rows):
        @dataclass(kw_only=True)
        class AllKeyword:
            name: str
            priority: int

        result = (
            DefaultsExample.query.order_by("name")
            .select(
                DefaultsExample.name, DefaultsExample.priority, result_type=AllKeyword
            )
            .first()
        )
        assert result == AllKeyword(name="alpha", priority=3)

    def test_positional_only_mixed_with_keyword_only(self, rows):
        """Neither the all-positional nor the all-keyword call works here."""

        @dataclass
        class Mixed:
            name: str
            priority: int

            def __init__(self, name: str, /, *, priority: int) -> None:
                self.name = name
                self.priority = priority

        result = (
            DefaultsExample.query.order_by("name")
            .select(DefaultsExample.name, DefaultsExample.priority, result_type=Mixed)
            .first()
        )
        assert result == Mixed("alpha", priority=3)

    def test_positional_or_keyword_mixed_with_keyword_only(self, rows):
        @dataclass
        class PartlyKwOnly:
            name: str
            priority: int = field(kw_only=True)

        result = (
            DefaultsExample.query.order_by("name")
            .select(
                DefaultsExample.name, DefaultsExample.priority, result_type=PartlyKwOnly
            )
            .first()
        )
        assert result == PartlyKwOnly(name="alpha", priority=3)


def test_select_result_type_rejects_a_variadic_constructor(rows):
    @dataclass(init=False)
    class Variadic:
        name: str

        def __init__(self, *args: object) -> None:
            self.name = str(args[0])

    with pytest.raises(TypeError, match="fixed constructor signature"):
        DefaultsExample.query.select(DefaultsExample.name, result_type=Variadic)


class TestSelectTwiceIsAlwaysLastWins:
    """Re-selecting replaces the columns, whatever either side is made of.

    The internal alias a selected expression gets used to restart its counter
    from 1 on every select(), so a second expression column regenerated the
    first one's alias and collided with it -- a ValueError blaming "a field on
    the model" that named neither the real cause nor a real field.
    """

    @pytest.fixture
    def ordered(self, db):
        # LOWER(name) and UPPER(status) disagree about order, so a test can
        # tell which one a query actually used.
        DefaultsExample.query.create(name="zzz", priority=1, status="aaa")
        DefaultsExample.query.create(name="aaa", priority=2, status="zzz")

    def test_field_then_field(self, ordered):
        result = (
            DefaultsExample.query.order_by("name")
            .select(DefaultsExample.name)
            .select(DefaultsExample.priority)
        )
        assert list(result) == [(2,), (1,)]

    def test_field_then_expression(self, ordered):
        result = (
            DefaultsExample.query.order_by("name")
            .select(DefaultsExample.name)
            .select(Upper("name"))
        )
        assert list(result) == [("AAA",), ("ZZZ",)]

    def test_expression_then_field(self, ordered):
        result = (
            DefaultsExample.query.order_by("name")
            .select(Upper("name"))
            .select(DefaultsExample.name)
        )
        assert list(result) == [("aaa",), ("zzz",)]

    def test_expression_then_same_expression_function(self, ordered):
        """The reported crash: both aliases wanted to be 'upper1'."""
        result = (
            DefaultsExample.query.order_by("name")
            .select(Upper("name"))
            .select(Upper("status"))
        )
        assert list(result) == [("ZZZ",), ("AAA",)]

    def test_expression_then_different_expression_function(self, ordered):
        result = (
            DefaultsExample.query.order_by("name")
            .select(Upper("name"))
            .select(Lower("status"))
        )
        assert list(result) == [("zzz",), ("aaa",)]

    def test_f_then_f(self, ordered):
        result = (
            DefaultsExample.query.order_by("name")
            .select(F("priority"))
            .select(F("name"))
        )
        assert list(result) == [("aaa",), ("zzz",)]

    def test_mixed_list_then_mixed_list(self, ordered):
        result = (
            DefaultsExample.query.order_by("name")
            .select(DefaultsExample.name, Upper("status"))
            .select(DefaultsExample.priority, Lower("name"))
        )
        assert list(result) == [(2, "aaa"), (1, "zzz")]

    def test_flat_then_flat(self, ordered):
        result = (
            DefaultsExample.query.order_by("name")
            .select(Upper("name"), flat=True)
            .select(Upper("status"), flat=True)
        )
        assert list(result) == ["ZZZ", "AAA"]

    def test_expression_then_result_type(self, ordered):
        @dataclass
        class NameAndUpper:
            name: str
            upper: str

        result = (
            DefaultsExample.query.order_by("name")
            .select(Upper("name"))
            .select(DefaultsExample.name, Upper("status"), result_type=NameAndUpper)
        )
        assert list(result) == [
            NameAndUpper(name="aaa", upper="ZZZ"),
            NameAndUpper(name="zzz", upper="AAA"),
        ]

    def test_three_selects_in_a_row(self, ordered):
        result = (
            DefaultsExample.query.order_by("name")
            .select(Upper("name"))
            .select(Upper("status"))
            .select(Upper("name"))
        )
        assert list(result) == [("AAA",), ("ZZZ",)]

    def test_aggregates_still_work_after_re_selecting(self, ordered):
        rows = DefaultsExample.query.select(Upper("name")).select(Upper("status"))
        assert rows.count() == 2
        assert rows.exists() is True


class TestInternalAliasesNeverClobberUserAnnotations:
    """A selected expression gets an internal alias, and that alias must not
    land on one the caller already chose -- doing so silently redefines what
    order_by()/filter() on that name mean."""

    @pytest.fixture
    def ordered(self, db):
        DefaultsExample.query.create(name="zzz", priority=1, status="aaa")
        DefaultsExample.query.create(name="aaa", priority=2, status="zzz")

    def test_order_by_a_user_annotation_keeps_its_meaning(self, ordered):
        """'upper1' is what the generator would have produced for Upper(...),
        so an unguarded generator overwrote LOWER(name) with UPPER(status) and
        silently reversed the order."""
        result = (
            DefaultsExample.query.annotate(upper1=Lower("name"))
            .order_by("upper1")
            .select(DefaultsExample.name, Upper("status"))
        )
        assert [row[0] for row in result] == ["aaa", "zzz"]

    def test_filter_on_a_user_annotation_keeps_its_meaning(self, ordered):
        result = (
            DefaultsExample.query.annotate(upper1=Lower("name"))
            .filter(upper1="aaa")
            .select(DefaultsExample.name, Upper("status"))
        )
        assert list(result) == [("aaa", "ZZZ")]


class TestColumnsBelongToTheirModel:
    """`select()`'s half of the guard `where()` carries.

    `Field[T]` carries no model identity, so nothing stops one model's field
    being handed to another model's `select()`. The name then resolves against
    the queried model -- silently the wrong column when both have one.
    `Widget` is the other model here because it also has a `name`.
    """

    def test_same_model_column_passes(self, rows):
        result = DefaultsExample.query.order_by("name").select(
            DefaultsExample.name, flat=True
        )
        assert list(result) == ["alpha", "beta", "gamma"]

    def test_other_model_column_raises_although_the_name_exists(self, rows):
        """The dangerous case: both models have a `name`, so without the check
        this quietly selected DefaultsExample.name."""
        with pytest.raises(TypeError) as excinfo:
            DefaultsExample.query.select(Widget.name)
        message = str(excinfo.value)
        assert "Widget.name" in message
        assert "DefaultsExample queryset" in message

    def test_other_model_column_raises_when_the_name_does_not_exist(self, rows):
        """Previously a FieldError from deep in the compiler."""
        with pytest.raises(TypeError, match="Widget.size"):
            DefaultsExample.query.select(Widget.size)

    def test_traversed_column_rooted_elsewhere_raises_as_cross_model(self, rows):
        """Being another model's column is the root mistake, so it is named
        ahead of the traversal refusal -- "select columns on the queried
        model" would be advice that doesn't help here."""
        with pytest.raises(TypeError, match="WidgetTag.widget__name"):
            DefaultsExample.query.select(WidgetTag.widget.name)

    def test_another_models_key_column_raises_as_cross_model(self, rows):
        """A foreign key's key column is selectable, but only on the queryset
        it belongs to -- the guard runs before the column resolves, so it
        still catches one rooted elsewhere."""
        with pytest.raises(TypeError, match="WidgetTag.widget__id"):
            DefaultsExample.query.select(WidgetTag.widget.id)

    def test_traversed_column_on_its_own_root_still_reports_traversal(self, db):
        with pytest.raises(TypeError, match="reached through a relation"):
            WidgetTag.query.select(WidgetTag.widget.name)

    def test_expressions_are_unaffected(self, rows):
        """An expression takes a string resolved against whatever query it
        lands in, like filter()'s kwargs -- there is no origin to check."""
        assert list(
            DefaultsExample.query.order_by("name").select(F("priority"), flat=True)
        ) == [3, 1, 2]
        assert list(
            DefaultsExample.query.order_by("name").select(Upper("name"), flat=True)
        ) == ["ALPHA", "BETA", "GAMMA"]

    def test_mixed_list_with_one_foreign_column_raises(self, rows):
        with pytest.raises(TypeError, match="Widget.name"):
            DefaultsExample.query.select(DefaultsExample.priority, Widget.name)


def test_select_rejects_a_field_read_off_a_mixin(db):
    """The mixin holds the declaration; only the model that mixes it in has an
    attached, named copy. This used to surface as a bare AssertionError.

    A checker rejects the access too (`__get__` wants `owner: type[Model]`,
    and a mixin isn't one), so this is the backstop for an untyped call site
    rather than the only guard.
    """
    with pytest.raises(TypeError, match="unattached"):
        MixinTestModel.query.select(TimestampMixin.created_at)  # ty: ignore[invalid-attribute-access]


def test_select_accepts_the_same_field_off_the_model(db):
    MixinTestModel.query.create(name="a")
    assert len(list(MixinTestModel.query.select(MixinTestModel.created_at))) == 1


def test_select_alias_skips_a_column_that_looks_like_one(db):
    """A model is free to have columns named `upper1` and `f1`; a generated
    alias must step over them rather than shadow a real column."""
    AliasCollisionExample.query.create(name="a", upper1="real-upper1", f1="real-f1")

    result = AliasCollisionExample.query.select(
        AliasCollisionExample.upper1, Upper("name")
    )
    assert list(result) == [("real-upper1", "A")]

    result = AliasCollisionExample.query.select(AliasCollisionExample.f1, F("name"))
    assert list(result) == [("real-f1", "a")]


class TestMergingRowAndModelQuerysets:
    """Merging a row-mode queryset with a model-mode one produces a query
    neither side describes. The guard only looked at the left operand, so
    `model_qs | row_qs` recursed until the stack ran out."""

    def test_model_or_row_raises(self, rows):
        with pytest.raises(TypeError, match="must involve the same values"):
            DefaultsExample.query.all() | DefaultsExample.query.select(
                DefaultsExample.name
            )

    def test_row_or_model_raises(self, rows):
        with pytest.raises(TypeError, match="must involve the same values"):
            (
                DefaultsExample.query.select(DefaultsExample.name)
                | DefaultsExample.query.all()
            )

    def test_model_and_row_raises(self, rows):
        with pytest.raises(TypeError, match="must involve the same values"):
            DefaultsExample.query.all() & DefaultsExample.query.select(
                DefaultsExample.name
            )

    def test_sliced_row_queryset_merges(self, rows):
        """A sliced left operand is re-expressed as an id subquery, which used
        to call the public values() and hit select()'s own refusal."""
        r = DefaultsExample.query.order_by("name").select(DefaultsExample.name)
        assert len(list(r[0:1] | r)) == 3
        assert len(list(r | r[0:1])) == 3

    def test_different_row_shapes_do_not_merge(self, rows):
        """Same columns, different rows: tuple, flat and result_type= select
        identically and differ only in how each row is built, so a merge used
        to hand back whichever shape the left operand carried."""

        @dataclass
        class NameOnly:
            name: str

        tuples = DefaultsExample.query.select(DefaultsExample.name)
        flat = DefaultsExample.query.select(DefaultsExample.name, flat=True)
        dataclasses_ = DefaultsExample.query.select(
            DefaultsExample.name, result_type=NameOnly
        )

        for left, right in (
            (dataclasses_, tuples),
            (tuples, dataclasses_),
            (tuples, flat),
            (flat, tuples),
        ):
            with pytest.raises(TypeError, match="same row shape"):
                left | right

    def test_matching_row_shapes_still_merge(self, rows):
        @dataclass
        class NameOnly:
            name: str

        left = DefaultsExample.query.select(DefaultsExample.name, result_type=NameOnly)
        right = DefaultsExample.query.select(DefaultsExample.name, result_type=NameOnly)
        assert len(list(left | right)) == 3

    def test_matching_sides_still_merge(self, rows):
        model = DefaultsExample.query.all() | DefaultsExample.query.all()
        assert len(list(model)) == 3
        row = DefaultsExample.query.select(
            DefaultsExample.name
        ) | DefaultsExample.query.select(DefaultsExample.name)
        assert len(list(row)) == 3


class TestSelectTwiceWithExpressions:
    """`select()` twice is last-wins, and that has to hold for expression
    columns too. `_values_list` aliases an expression by annotating
    internally, which used to call the *public* annotate() and so trip
    RowQuerySet's guard -- a guard meant for callers adding a column to a
    finished row, not for select() rebuilding one."""

    def test_replacing_fields_with_an_expression(self, rows):
        result = (
            DefaultsExample.query.order_by("name")
            .select(DefaultsExample.name)
            .select(F("priority"))
        )
        assert list(result) == [(3,), (1,), (2,)]

    def test_replacing_fields_with_a_flat_expression(self, rows):
        result = (
            DefaultsExample.query.order_by("name")
            .select(DefaultsExample.name)
            .select(F("priority"), flat=True)
        )
        assert list(result) == [3, 1, 2]

    def test_replacing_fields_with_an_expression_and_result_type(self, rows):
        @dataclass
        class NameAndExpr:
            name: str
            upper: str

        result = (
            DefaultsExample.query.order_by("name")
            .select(DefaultsExample.priority)
            .select(DefaultsExample.name, Upper("name"), result_type=NameAndExpr)
            .first()
        )
        assert result == NameAndExpr(name="alpha", upper="ALPHA")

    def test_annotate_is_still_refused_for_callers(self, rows):
        """The guard the internal path now bypasses is still there."""
        with pytest.raises(TypeError, match="Annotate first, then select"):
            DefaultsExample.query.select(DefaultsExample.name).annotate(x=Value(1))


class TestPrefetchAndSelect:
    """A prefetch hangs related objects off each result's attributes, and a
    row has nowhere to put them: it was silently wasted work for tuples and
    scalars, and an AttributeError for result_type=. Refused in both orders,
    the same as join()."""

    @pytest.fixture
    def widget(self, db):
        w = Widget.query.create(name="w", size="s")
        tag = Tag.query.create(name="t")
        w.tags.add(tag)
        return w

    def test_select_after_prefetch_raises_in_tuple_mode(self, widget):
        with pytest.raises(TypeError, match="after prefetch"):
            Widget.query.prefetch("tags").select(Widget.name)

    def test_select_after_prefetch_raises_in_flat_mode(self, widget):
        with pytest.raises(TypeError, match="after prefetch"):
            Widget.query.prefetch("tags").select(Widget.name, flat=True)

    def test_select_after_prefetch_raises_in_result_type_mode(self, widget):
        @dataclass
        class NameRow:
            name: str

        with pytest.raises(TypeError, match="after prefetch"):
            Widget.query.prefetch("tags").select(Widget.name, result_type=NameRow)

    def test_prefetch_after_select_raises(self, widget):
        with pytest.raises(TypeError, match="after select"):
            Widget.query.select(Widget.name).prefetch("tags")

    def test_prefetch_without_select_is_unaffected(self, widget):
        widgets = list(Widget.query.prefetch("tags"))
        assert [t.name for t in widgets[0].tags.query.all()] == ["t"]


class TestAnnotateAfterSelect:
    """An annotation appends a column, so it would change the row shape out
    from under the type select() already declared. The supported order is
    annotate first, then select()."""

    def test_annotate_after_select_raises(self, rows):
        with pytest.raises(TypeError, match="Annotate first, then select"):
            DefaultsExample.query.select(DefaultsExample.name).annotate(x=Value(1))

    def test_annotate_after_select_raises_in_result_type_mode(self, rows):
        with pytest.raises(TypeError, match="Annotate first, then select"):
            DefaultsExample.query.select(
                DefaultsExample.name, DefaultsExample.priority, result_type=NameStat
            ).annotate(x=Value(1))

    def test_annotate_after_select_raises_in_flat_mode(self, rows):
        with pytest.raises(TypeError, match="Annotate first, then select"):
            DefaultsExample.query.select(DefaultsExample.name, flat=True).annotate(
                x=Value(1)
            )

    def test_annotate_before_select_still_works(self, rows):
        """The supported order — the annotation is selectable as a column."""
        result = (
            DefaultsExample.query.annotate(n=Count("id"))
            .order_by("name")
            .select(DefaultsExample.name)
        )
        assert list(result) == [("alpha",), ("beta",), ("gamma",)]

    def test_annotate_is_unaffected_on_a_plain_queryset(self, rows):
        assert DefaultsExample.query.annotate(n=Count("id")).count() == 3


def test_get_or_create_after_select_raises(db):
    with pytest.raises(TypeError, match="get_or_create"):
        DefaultsExample.query.select(DefaultsExample.name).get_or_create(name="x")


def test_bulk_update_after_select_raises_before_any_sql(db):
    """The base would reach the same refusal, but only from the update()
    inside its own `transaction.atomic(savepoint=False)` -- which leaves the
    enclosing transaction unusable, so the *next* query fails too."""
    DefaultsExample.query.create(name="alpha", priority=3)
    objs = list(DefaultsExample.query.all())
    for obj in objs:
        obj.name = "changed"

    with pytest.raises(TypeError, match="bulk_update"):
        DefaultsExample.query.select(DefaultsExample.name).bulk_update(objs, ["name"])

    # The transaction is still usable: nothing was sent.
    assert DefaultsExample.query.count() == 1
    assert DefaultsExample.query.get().name == "alpha"


def test_returning_after_select_raises(db):
    with pytest.raises(TypeError, match="returning"):
        DefaultsExample.query.select(DefaultsExample.name).returning()


def test_select_after_returning_raises(db):
    with pytest.raises(TypeError, match="after returning"):
        DefaultsExample.query.returning().select(DefaultsExample.name)


def test_returning_without_select_is_unaffected(db):
    DefaultsExample.query.create(name="alpha", priority=3)
    updated = DefaultsExample.query.returning().update(name="beta")
    assert [obj.name for obj in updated] == ["beta"]


def test_upsert_after_select_raises(db):
    with pytest.raises(TypeError, match="upsert"):
        DefaultsExample.query.select(DefaultsExample.name).upsert(
            name="x", unique_fields=[DefaultsExample.name]
        )


def test_bulk_upsert_after_select_raises(db):
    with pytest.raises(TypeError, match="bulk_upsert"):
        DefaultsExample.query.select(DefaultsExample.name).bulk_upsert(
            [DefaultsExample(name="x")],
            update_fields=[DefaultsExample.priority],
            unique_fields=[DefaultsExample.name],
        )


def test_select_after_values_raises(db):
    with pytest.raises(TypeError, match="after values"):
        DefaultsExample.query.values("name").select(DefaultsExample.name)


def test_values_after_select_raises(db):
    with pytest.raises(TypeError, match="after select"):
        DefaultsExample.query.select(DefaultsExample.name).values("name")


def test_create_after_select_raises(db):
    with pytest.raises(TypeError, match="create"):
        DefaultsExample.query.select(DefaultsExample.name).create(name="x")


def test_bulk_create_after_select_raises(db):
    with pytest.raises(TypeError, match="bulk_create"):
        DefaultsExample.query.select(DefaultsExample.name).bulk_create(
            [DefaultsExample(name="x")]
        )


def test_update_after_select_raises(db):
    with pytest.raises(TypeError, match="update"):
        DefaultsExample.query.select(DefaultsExample.name).update(name="x")


def test_delete_after_select_raises(db):
    with pytest.raises(TypeError, match="delete"):
        DefaultsExample.query.select(DefaultsExample.name).delete()


def test_update_refuses_any_row_mode_queryset(db):
    """select() shares delete()'s guard rather than adding its own, so
    update() now refuses values()/values_list() for the same reason."""
    with pytest.raises(TypeError, match="Cannot call update"):
        DefaultsExample.query.values("name").update(name="x")
    with pytest.raises(TypeError, match="Cannot call update"):
        DefaultsExample.query.values_list("name").update(name="x")


def test_select_twice_last_wins(rows):
    result = (
        DefaultsExample.query.order_by("name")
        .select(DefaultsExample.name)
        .select(DefaultsExample.priority, flat=True)
    )
    assert list(result) == [3, 1, 2]
