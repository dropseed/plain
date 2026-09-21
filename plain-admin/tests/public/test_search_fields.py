"""`search_fields` accepts a field reference wherever it accepted a string.

The contract is that the spelling is invisible to the database: declaring
`PinnedNavItem.view_slug` and declaring `"view_slug"` build the same query,
and a traversed reference (`PinnedNavItem.user.username`) builds the same
query as the path it stands for. A reference to another model's field is
refused when the class is defined.
"""

from __future__ import annotations

import pytest
from app.users.models import User
from plain.admin.models import PinnedNavItem
from plain.admin.views import AdminModelListView
from plain.postgres import QuerySet
from plain.test import RequestFactory


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
    assert StringSearch.get_search_fields() == ("view_slug", "user__username")
    assert FieldRefSearch.get_search_fields() == ("view_slug", "user__username")


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
