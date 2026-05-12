"""Contract tests for `reverse()` round-trips.

`reverse()` is contract: views and templates rely on the return value.
These pin current behavior across slash variations and include()
boundaries so subsequent routing changes don't silently shift what URLs
get rendered into HTML.
"""

from __future__ import annotations

import pytest

from plain.runtime import settings
from plain.urls import reverse
from plain.urls.exceptions import NoReverseMatch
from plain.urls.resolvers import _get_cached_resolver


@pytest.fixture
def slash_router():
    original = settings.URLS_ROUTER
    settings.URLS_ROUTER = "slash_routers.SlashRouter"
    _get_cached_resolver.cache_clear()
    try:
        yield
    finally:
        settings.URLS_ROUTER = original
        _get_cached_resolver.cache_clear()


@pytest.fixture
def boundary_router():
    original = settings.URLS_ROUTER
    settings.URLS_ROUTER = "boundary_routers.BoundaryRouter"
    _get_cached_resolver.cache_clear()
    try:
        yield
    finally:
        settings.URLS_ROUTER = original
        _get_cached_resolver.cache_clear()


def test_reverse_route_with_slash(slash_router):
    """`path("with-slash/")` → `reverse()` returns `/with-slash/`."""
    assert reverse("with-slash") == "/with-slash/"


def test_reverse_route_without_slash(slash_router):
    """`path("without-slash")` → `reverse()` returns `/without-slash` (no trailing slash)."""
    assert reverse("without-slash") == "/without-slash"


def test_reverse_through_canonical_include(boundary_router):
    """`include("admin-canonical/", ...)` + child `path("home/")` → `/admin-canonical/home/`."""
    assert reverse("admin-canonical:home") == "/admin-canonical/home/"


def test_reverse_through_nested_include(boundary_router):
    """Nested include — `/admin-canonical/nested/users/` resolves through chained includes."""
    assert reverse("admin-canonical:users-list") == "/admin-canonical/nested/users/"
    assert (
        reverse("admin-canonical:user-detail", user_id=42)
        == "/admin-canonical/nested/users/42/"
    )


def test_reverse_through_boundary_include_no_slash(boundary_router):
    """`include("admin-boundary", ...)` (no trailing slash) — pin what reverse() does.

    Step #1 of the URL routing arc normalizes `include("admin-boundary")` to
    `include("admin-boundary/")`. Today's behavior pinned here may flip then.
    """
    assert reverse("admin-boundary:home") == "/admin-boundaryhome/"


def test_reverse_through_root_include(boundary_router):
    """`include("", ...)` adds no prefix — child route is reachable at its bare path."""
    assert reverse("root-include:hello") == "/root-hello/"


def test_reverse_through_leading_slash_include(boundary_router):
    """`include("/admin-leading/", ...)` produces a broken URL via `reverse()`.

    `reverse()` joins `/` (root prefix) with the include pattern, then
    `escape_leading_slashes` (a scheme-relative-URL safety pass) percent-encodes
    the doubled leading slash → `/%2Fadmin-leading/home/`. Step #1 normalizes
    leading slashes off include() arguments; after that this returns
    `/admin-leading/home/` cleanly.
    """
    assert reverse("admin-leading:home") == "/%2Fadmin-leading/home/"


def test_reverse_unknown_name_raises(slash_router):
    with pytest.raises(NoReverseMatch):
        reverse("not-a-real-name")
