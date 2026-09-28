"""`search_fields` accepts a field reference wherever it accepted a string.

The contract is that the spelling is invisible to the database: declaring
`PinnedNavItem.view_slug` and declaring `"view_slug"` build the same query,
and a traversed reference (`PinnedNavItem.user.username`) builds the same
query as the path it stands for. A reference to another model's field is
refused when the class is defined.
"""

import pytest
from app.users.models import User
from plain.admin.cards import TrendCard
from plain.admin.field_refs import FieldRef
from plain.admin.models import PinnedNavItem
from plain.admin.views import AdminModelListView
from plain.postgres import Field, QuerySet, types
from plain.test import RequestFactory

from plain import postgres


class StringSearch(AdminModelListView):
    model = PinnedNavItem
    title = "String search"
    search_fields = ("view_slug", "user__username")


class FieldRefSearch(AdminModelListView):
    model = PinnedNavItem
    title = "Field ref search"
    # `username` is a column on this test app's User. A checker run over this
    # repo resolves `app.users.models` to the example app's User instead,
    # which has no `username` -- the reference itself is ordinary.
    search_fields = (
        PinnedNavItem.view_slug,
        PinnedNavItem.user.username,  # ty: ignore[unresolved-attribute]
    )


class LocalFieldRefSearch(AdminModelListView):
    model = PinnedNavItem
    title = "Local field ref search"
    search_fields = (PinnedNavItem.view_slug,)


class TraversedFieldRefSearch(AdminModelListView):
    model = PinnedNavItem
    title = "Traversed field ref search"
    search_fields = (PinnedNavItem.user.username,)  # ty: ignore[unresolved-attribute]


def searched(
    view_class: type[AdminModelListView], term: str
) -> QuerySet[PinnedNavItem]:
    view = view_class(request=RequestFactory().get(f"/?search={term}"))
    return view.search_queryset(PinnedNavItem.query.all())


def test_field_references_normalize_to_lookup_paths() -> None:
    """Converged when the class is defined, so nothing downstream sees a Field.

    Leaving one on the class attribute would leave a live data descriptor
    there, and `self.search_fields` would run it.
    """
    assert StringSearch.search_fields == ("view_slug", "user__username")
    assert FieldRefSearch.search_fields == ("view_slug", "user__username")


def test_a_field_reference_builds_the_same_sql_as_the_string() -> None:
    """The whole point: the declaration spelling never reaches the database."""
    assert str(searched(FieldRefSearch, "alpha").sql_query) == str(
        searched(StringSearch, "alpha").sql_query
    )


def test_a_field_reference_searches_the_column(db) -> None:
    user = User.query.create(username="searchable")
    pinned = PinnedNavItem.query.create(user=user, view_slug="alpha_view")
    PinnedNavItem.query.create(user=user, view_slug="beta_view")

    assert [p.id for p in searched(LocalFieldRefSearch, "alpha")] == [pinned.id]


def test_a_traversed_field_reference_searches_through_the_relation(db) -> None:
    matching = User.query.create(username="matching")
    other = User.query.create(username="other")
    pinned = PinnedNavItem.query.create(user=matching, view_slug="shared")
    PinnedNavItem.query.create(user=other, view_slug="shared")

    # The join is what makes this a traversal rather than a local column.
    assert 'INNER JOIN "users_user"' in str(
        searched(TraversedFieldRefSearch, "matching").sql_query
    )
    assert [p.id for p in searched(TraversedFieldRefSearch, "matching")] == [pinned.id]


def test_a_string_search_field_still_works(db) -> None:
    user = User.query.create(username="searchable")
    pinned = PinnedNavItem.query.create(user=user, view_slug="alpha_view")
    PinnedNavItem.query.create(user=user, view_slug="beta_view")

    assert [p.id for p in searched(StringSearch, "alpha_view")] == [pinned.id]


def test_a_field_from_another_model_is_refused_at_class_definition() -> None:
    with pytest.raises(TypeError, match="references PinnedNavItem.view_slug"):

        class CrossModel(AdminModelListView):
            model = User
            title = "Cross model"
            search_fields = (PinnedNavItem.view_slug,)


def test_a_traversed_field_from_another_model_is_refused() -> None:
    """A traversed reference belongs to the model the traversal started from."""
    with pytest.raises(TypeError, match="references PinnedNavItem.user__id"):

        class CrossModel(AdminModelListView):
            model = User
            title = "Cross model traversed"
            search_fields = (PinnedNavItem.user.id,)


class PropertySearch(AdminModelListView):
    model = PinnedNavItem
    title = "Property search"

    @property
    def search_fields(self) -> tuple[FieldRef, ...]:
        return (PinnedNavItem.view_slug,)


class PinnedTrendCard(TrendCard):
    title = "Pinned"
    model = PinnedNavItem
    datetime_field = PinnedNavItem.created_at


def test_an_instance_can_replace_search_fields(db) -> None:
    """Configuration set per request has to reach the query, as it always did."""
    matching = User.query.create(username="matching")
    other = User.query.create(username="other")
    pinned = PinnedNavItem.query.create(user=matching, view_slug="shared")
    PinnedNavItem.query.create(user=other, view_slug="shared")

    view = LocalFieldRefSearch(request=RequestFactory().get("/?search=matching"))
    view.search_fields = (PinnedNavItem.user.username,)  # ty: ignore[unresolved-attribute]

    assert view.get_search_fields() == ("user__username",)
    assert [p.id for p in view.search_queryset(PinnedNavItem.query.all())] == [
        pinned.id
    ]


def test_an_instance_can_replace_queryset_order() -> None:
    view = LocalFieldRefSearch(request=RequestFactory().get("/"))
    view.queryset_order = (PinnedNavItem.view_slug,)

    assert view.get_queryset_order() == ("view_slug",)
    assert 'ORDER BY "plainadmin_pinnednavitem"."view_slug" ASC' in str(
        view.order_queryset(PinnedNavItem.query.all()).sql_query
    )


def test_a_property_declaration_is_normalized_at_runtime() -> None:
    """A property computes its value per instance, so class definition skips it."""
    view = PropertySearch(request=RequestFactory().get("/?search=alpha"))

    assert view.get_search_fields() == ("view_slug",)


def test_a_card_converges_its_declared_datetime_field() -> None:
    # Read straight out of the class dict: the point is that the attribute
    # itself is a path now, not the `Field` the class body named.
    assert vars(PinnedTrendCard)["datetime_field"] == "created_at"
    assert PinnedTrendCard().get_datetime_field() == "created_at"


def test_a_card_instance_can_set_its_group_field() -> None:
    card = PinnedTrendCard()
    assert card.get_group_field() is None

    # Both suppressions are about the declared type, not the runtime: the
    # declaration accepts a `Field`, which is a data descriptor, so a checker
    # reads any assignment to the attribute as a descriptor `__set__`. By this
    # point the class attribute is a converged path and there is nothing
    # descriptor-shaped left to run.
    card.group_field = "view_slug"  # ty: ignore[invalid-assignment]
    assert card.get_group_field() == "view_slug"

    card.group_field = PinnedNavItem.view_slug  # ty: ignore[invalid-assignment]
    assert card.get_group_field() == "view_slug"


def test_an_unattached_mixin_field_is_refused() -> None:
    """Only the model that mixes it in has an attached, named copy.

    Left alone the reference normalizes to an empty lookup path and fails much
    later with `FieldError: Cannot resolve keyword ''`.
    """

    class NamedMixin(postgres.ModelMixin):
        name: Field[str] = types.TextField(max_length=50)

    with pytest.raises(TypeError, match="unattached"):

        class MixinSearch(AdminModelListView):
            model = PinnedNavItem
            title = "Mixin search"
            search_fields = (NamedMixin.name,)  # ty: ignore[invalid-attribute-access]
