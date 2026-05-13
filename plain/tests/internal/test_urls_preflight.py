"""Pin URL preflight and registration-time validation behavior.

`path()` and `include()` accept only string routes. Most invalid patterns
fail loudly at registration time (`ImproperlyConfigured`) rather than via
preflight — preflight is only used for things that can't be caught
statically, like name collisions with the namespace separator.

Registration-time guards (raise `ImproperlyConfigured`):

- `<wat:id>` — unknown converter
- `<int:1bad>` — parameter name isn't a valid Python identifier
- `<int: id>` — whitespace inside `<…>`
- `prefix-<int:id>` — mixed literal + converter in one segment
- `<path:rest>/more` — multi-segment capture not at the terminal position
- `<int:id>/<int:id>/` — duplicate parameter name
- `?` or `#` anywhere in the route
- Two `include()`s under one parent sharing a namespace

Preflight (warning):

- `urls.pattern_name_contains_colon` — `name="foo:bar"` clashes with the
  namespace separator
"""

from __future__ import annotations

import pytest

from plain.exceptions import ImproperlyConfigured
from plain.urls import Router, include, path
from plain.views import View


class _View(View):
    def get(self):
        return None


def _pattern_ids(results):
    return {r.id for r in results}


def test_path_with_leading_slash_emits_no_warning():
    """The constructor silently normalizes; no preflight noise."""
    url = path("/admin/", _View)
    assert _pattern_ids(url.preflight()) == set()


def test_pattern_name_contains_colon_fires():
    """Names with `:` clash with namespace separators."""
    url = path("admin/", _View, name="foo:bar")
    assert "urls.pattern_name_contains_colon" in _pattern_ids(url.preflight())


def test_pattern_name_without_colon_is_silent():
    url = path("admin/", _View, name="foo-bar")
    assert "urls.pattern_name_contains_colon" not in _pattern_ids(url.preflight())


def test_duplicate_parameter_name_raises():
    with pytest.raises(ImproperlyConfigured, match="more than once"):
        path("items/<int:id>/<int:id>/", _View)


def test_duplicate_parameter_name_across_converter_types_raises():
    """Same name, different converter — still a collision."""
    with pytest.raises(ImproperlyConfigured, match="more than once"):
        path("items/<int:id>/<slug:id>/", _View)


def test_question_mark_in_route_raises():
    with pytest.raises(ImproperlyConfigured, match=r"'\?' or '#'"):
        path("search?q=foo/", _View)


def test_hash_in_route_raises():
    with pytest.raises(ImproperlyConfigured, match=r"'\?' or '#'"):
        path("about#contact/", _View)


def test_duplicate_namespace_among_includes_raises():
    """Two `include()`s under one router sharing a namespace is always a
    mistake (one side is unreachable from `reverse()`) — registration-time
    error, not just a preflight warning."""
    child_urls = [path("home/", _View, name="home")]

    class _ChildRouter(Router):
        namespace = "shared"
        urls = child_urls

    class _ParentRouter(Router):
        namespace = ""
        urls = [
            include("a/", _ChildRouter),
            include("b/", _ChildRouter),
        ]

    from plain.urls.resolvers import URLResolver
    from plain.urls.segments import _route_to_segments

    with pytest.raises(ImproperlyConfigured, match="Namespace 'shared'"):
        URLResolver(
            segments=_route_to_segments(""), raw_route="", router=_ParentRouter()
        )


def test_duplicate_namespace_through_unnamespaced_include_raises():
    """The collision check also fires when the same namespace reaches the
    parent through two different paths — one direct, one bubbled up
    through an un-namespaced ancestor include()."""

    class _Inner(Router):
        namespace = "shared"
        urls = [path("home/", _View, name="home")]

    class _UnnamespacedMiddle(Router):
        namespace = ""
        urls = [include("inner/", _Inner)]

    class _ParentRouter(Router):
        namespace = ""
        urls = [
            include("a/", _UnnamespacedMiddle),
            include("b/", _Inner),
        ]

    from plain.urls.resolvers import URLResolver
    from plain.urls.segments import _route_to_segments

    with pytest.raises(ImproperlyConfigured, match="Namespace 'shared'"):
        URLResolver(
            segments=_route_to_segments(""), raw_route="", router=_ParentRouter()
        )


def test_distinct_namespaces_silent():
    class _ChildA(Router):
        namespace = "alpha"
        urls = [path("home/", _View, name="home")]

    class _ChildB(Router):
        namespace = "beta"
        urls = [path("home/", _View, name="home")]

    class _ParentRouter(Router):
        namespace = ""
        urls = [include("a/", _ChildA), include("b/", _ChildB)]

    from plain.urls.resolvers import URLResolver
    from plain.urls.segments import _route_to_segments

    # Construction succeeds with no collision.
    URLResolver(segments=_route_to_segments(""), raw_route="", router=_ParentRouter())
