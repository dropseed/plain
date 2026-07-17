"""Contract tests for `ResolverMatch.namespaced_url_name`.

`request.resolver_match.namespaced_url_name` carries the namespace-qualified
name of the matched route (e.g. `"admin:home"`). The admin tooling, CLI
output, and user middleware that branches on the matched route all rely on
this being populated correctly for both direct and nested patterns under a
namespaced router.
"""

from __future__ import annotations

from contextlib import contextmanager

from plain.runtime import settings
from plain.urls import get_resolver
from plain.urls.resolvers import _get_cached_resolver


@contextmanager
def boundary_resolver():
    original = settings.URLS_ROUTER
    original_ts = settings.URLS_TRAILING_SLASH
    settings.URLS_ROUTER = "boundary_routers.BoundaryRouter"
    settings.URLS_TRAILING_SLASH = True
    _get_cached_resolver.cache_clear()
    try:
        yield get_resolver()
    finally:
        settings.URLS_ROUTER = original
        settings.URLS_TRAILING_SLASH = original_ts
        _get_cached_resolver.cache_clear()


def test_direct_route_under_namespaced_include_carries_namespace():
    """`include("admin-canonical/", AdminCanonicalRouter)` where AdminCanonicalRouter
    has `namespace="admin-canonical"` and a direct `path("home/", ..., name="home")`.
    The match must report `namespaced_url_name == "admin-canonical:home"`.
    """
    with boundary_resolver() as resolver:
        match = resolver.resolve("/admin-canonical/home/")
        assert match.namespace == "admin-canonical"
        assert match.url_name == "home"
        assert match.namespaced_url_name == "admin-canonical:home"


def test_nested_include_under_namespace_carries_namespace():
    """Through a chained include — namespace still surfaces."""
    with boundary_resolver() as resolver:
        match = resolver.resolve("/admin-canonical/nested/users/")
        assert match.namespace == "admin-canonical"
        assert match.namespaced_url_name == "admin-canonical:users-list"


def test_unnamespaced_match_has_clean_namespaced_url_name():
    """A route directly under the root router (`namespace = ""`) must
    surface as a clean `namespaced_url_name` — just the name, no leading
    colon. The root's empty namespace, and any un-namespaced ancestor
    `include()`s, are filtered out by `ResolverMatch.__init__` so that
    `":".join(...)` doesn't leak a `:hello`-style result.

    `BoundaryRouter` registers `path("/leading-slash/", ..., name="leading-slash")`
    directly at the top level — no include in between — so the chain is
    exactly `root(ns="") → endpoint`.
    """
    with boundary_resolver() as resolver:
        match = resolver.resolve("/leading-slash/")
        assert match.namespace == ""
        assert match.namespaces == []
        assert match.url_name == "leading-slash"
        assert match.namespaced_url_name == "leading-slash"
