"""Pin URL preflight check behavior.

Internal because these tests pin which checks fire for which patterns —
implementation surface that will shift as the URL routing arc lands:

- `urls.pattern_starts_with_slash` — currently scoped to `APPEND_SLASH=True`
  (see `urls/patterns.py:34-37`). Step #1 makes leading slashes silently
  normalize, so the check changes meaning (or goes away).
- `urls.include_pattern_ends_with_dollar` — independent of slash changes,
  but still pinned for completeness.
- `urls.pattern_name_contains_colon` — same.
"""

from __future__ import annotations

import re

from plain.runtime import settings
from plain.urls import include, path
from plain.views import View


class _View(View):
    def get(self):
        return None


def _pattern_ids(results):
    return {r.id for r in results}


def test_pattern_starts_with_slash_fires_with_append_slash_on():
    original = settings.APPEND_SLASH
    settings.APPEND_SLASH = True
    try:
        url = path("/admin/", _View)
        results = url.preflight()
    finally:
        settings.APPEND_SLASH = original
    assert "urls.pattern_starts_with_slash" in _pattern_ids(results)


def test_pattern_starts_with_slash_silent_when_append_slash_off():
    """`APPEND_SLASH=False` deliberately skips this check.

    Reasoning at `urls/patterns.py:34-37`: when APPEND_SLASH is off, leading
    slashes can be useful. Step #2 removes `APPEND_SLASH` entirely; this
    check needs to be re-thought.
    """
    original = settings.APPEND_SLASH
    settings.APPEND_SLASH = False
    try:
        url = path("/admin/", _View)
        results = url.preflight()
    finally:
        settings.APPEND_SLASH = original
    assert "urls.pattern_starts_with_slash" not in _pattern_ids(results)


def test_pattern_starts_with_slash_silent_for_canonical_route():
    """No leading slash → no warning."""
    url = path("admin/", _View)
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
