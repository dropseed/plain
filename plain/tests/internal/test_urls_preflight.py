"""Pin URL preflight check behavior.

Internal because these tests pin which checks fire for which patterns —
implementation surface that will shift as the URL routing arc lands.

- `urls.pattern_starts_with_slash` — fires for `re.Pattern` routes that
  start with `/`. String routes are normalized at construction so the
  check is unreachable for them, but regex routes bypass normalization
  and can still trip the root resolver.
- `urls.include_pattern_ends_with_dollar` — fires for regex includes
  that anchor with `$`, which would prevent the resolver from
  continuing to child patterns.
- `urls.pattern_name_contains_colon` — names with `:` clash with the
  namespace separator and break `reverse()`.
"""

from __future__ import annotations

import re

from plain.urls import include, path
from plain.views import View


class _View(View):
    def get(self):
        return None


def _pattern_ids(results):
    return {r.id for r in results}


def test_path_with_leading_slash_emits_no_warning():
    """The constructor silently normalizes; no preflight noise.

    Before step #1 this fired `urls.pattern_starts_with_slash`. Now the
    leading slash is stripped at construction time and there's nothing
    to warn about.
    """
    url = path("/admin/", _View)
    assert _pattern_ids(url.preflight()) == set()


def test_include_with_dollar_residue_still_fires_migration_warning():
    """`include("admin/$", ...)` keeps the `$` so the migration warning fires.

    The normalizer would otherwise append `/` and turn `admin/$` into
    `admin/$/`, silencing `urls.path_migration_warning` even though the
    route would match a literal `$` segment.
    """
    resolver = include("admin/$", [path("home/", _View)])
    assert "urls.path_migration_warning" in _pattern_ids(resolver.pattern.preflight())


def test_include_with_caret_residue_still_fires_migration_warning():
    """`include("^admin", ...)` keeps the `^` for the same reason."""
    resolver = include("^admin", [path("home/", _View)])
    assert "urls.path_migration_warning" in _pattern_ids(resolver.pattern.preflight())


def test_regex_pattern_with_leading_slash_fires():
    """`re.Pattern` routes bypass `path()`/`include()` normalization, so a
    leading slash silently fails to match against the resolver. The
    preflight warning is the only place users get told.
    """
    url = path(re.compile(r"^/admin"), _View)
    assert "urls.pattern_starts_with_slash" in _pattern_ids(url.preflight())


def test_regex_pattern_without_leading_slash_is_silent():
    url = path(re.compile(r"^admin"), _View)
    assert "urls.pattern_starts_with_slash" not in _pattern_ids(url.preflight())


def test_include_pattern_ends_with_dollar_fires():
    """`include(re.compile(r"admin/$"), ...)` — the `$` anchor prevents continuation.

    The check lives on `RegexPattern.preflight` (not `RoutePattern`), so it
    only fires when an include is built from a compiled regex.
    """
    resolver = include(re.compile(r"admin/$"), [path("home/", _View)])
    results = resolver.pattern.preflight()
    assert "urls.include_pattern_ends_with_dollar" in _pattern_ids(results)


def test_include_pattern_without_dollar_is_silent():
    resolver = include(re.compile(r"admin/"), [path("home/", _View)])
    results = resolver.pattern.preflight()
    assert "urls.include_pattern_ends_with_dollar" not in _pattern_ids(results)


def test_pattern_name_contains_colon_fires():
    """Names with `:` clash with namespace separators."""
    url = path("admin/", _View, name="foo:bar")
    assert "urls.pattern_name_contains_colon" in _pattern_ids(url.preflight())


def test_pattern_name_without_colon_is_silent():
    url = path("admin/", _View, name="foo-bar")
    assert "urls.pattern_name_contains_colon" not in _pattern_ids(url.preflight())
