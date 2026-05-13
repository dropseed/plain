"""Pin URL preflight check behavior.

`path()` and `include()` accept only string routes, so the remaining
checks live on `RoutePattern` and `URLPattern`:

- `urls.path_migration_warning` — fires when a string route still looks
  like a Django-style regex (`^`, `$`, `(?P<`), which would match as
  literal characters rather than the user's intent.
- `urls.pattern_name_contains_colon` — names with `:` clash with the
  namespace separator and break `reverse()`.

Routes are normalized at construction time so leading slashes never
reach the resolver — there's no preflight noise to assert against.
"""

from __future__ import annotations

from plain.urls import include, path
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


def test_include_with_dollar_residue_fires_migration_warning():
    """`include("admin/$", ...)` keeps the `$` so the migration warning fires.

    The normalizer would otherwise append `/` and turn `admin/$` into
    `admin/$/`, silencing the warning even though the route would match
    a literal `$` segment.
    """
    resolver = include("admin/$", [path("home/", _View)])
    assert "urls.path_migration_warning" in _pattern_ids(resolver.pattern.preflight())


def test_include_with_caret_residue_fires_migration_warning():
    """`include("^admin", ...)` keeps the `^` for the same reason."""
    resolver = include("^admin", [path("home/", _View)])
    assert "urls.path_migration_warning" in _pattern_ids(resolver.pattern.preflight())


def test_pattern_name_contains_colon_fires():
    """Names with `:` clash with namespace separators."""
    url = path("admin/", _View, name="foo:bar")
    assert "urls.pattern_name_contains_colon" in _pattern_ids(url.preflight())


def test_pattern_name_without_colon_is_silent():
    url = path("admin/", _View, name="foo-bar")
    assert "urls.pattern_name_contains_colon" not in _pattern_ids(url.preflight())
