"""Unit tests for the segment parser used by `path()` and `include()`.

`_route_to_segments` is the bridge between the user-facing route grammar
(`users/<int:id>/`) and the internal segment list the resolver walks.
Internal because the segment tuple shape isn't part of the public API —
only the user-observable resolution behavior is.
"""

from __future__ import annotations

import pytest

from plain.exceptions import ImproperlyConfigured
from plain.urls.converters import INT, PATH, STR, UUID
from plain.urls.segments import (
    Capture,
    Literal,
    _route_to_segments,
)


def test_empty_route_has_no_segments():
    route = _route_to_segments("")
    assert route.segments == ()
    assert route.trailing_slash is False


def test_root_slash_only_route():
    """`path("/")` is normalized to `path("")` by `path()` before parsing,
    but parsing a literal `/` directly still produces empty segments with
    trailing_slash=True (the root case is irrelevant in practice)."""
    route = _route_to_segments("/")
    assert route.segments == ()
    assert route.trailing_slash is True


def test_single_literal_segment_no_trailing_slash():
    route = _route_to_segments("users")
    assert route.segments == (Literal(value="users"),)
    assert route.trailing_slash is False


def test_single_literal_segment_with_trailing_slash():
    route = _route_to_segments("users/")
    assert route.segments == (Literal(value="users"),)
    assert route.trailing_slash is True


def test_int_converter_segment():
    route = _route_to_segments("users/<int:id>/")
    assert route.segments == (Literal(value="users"), Capture(name="id", converter=INT))
    assert route.trailing_slash is True


def test_default_converter_is_str():
    """`<name>` without an explicit converter defaults to `str`."""
    route = _route_to_segments("users/<name>/")
    assert route.segments[1] == Capture(name="name", converter=STR)


def test_uuid_converter_segment():
    route = _route_to_segments("items/<uuid:id>/")
    assert route.segments[1] == Capture(name="id", converter=UUID)


def test_path_converter_is_multi_segment():
    """`<path:rest>` parses as a `Capture` whose converter is multi-segment —
    the segment consumes all remaining path components."""
    route = _route_to_segments("docs/<path:rest>")
    cap = route.segments[1]
    assert isinstance(cap, Capture)
    assert cap == Capture(name="rest", converter=PATH)
    assert cap.converter.multi_segment is True


def test_multi_segment_must_be_terminal():
    """A multi-segment capture that isn't the last segment is rejected."""
    with pytest.raises(ImproperlyConfigured, match="must be terminal"):
        _route_to_segments("docs/<path:rest>/more")


def test_unknown_converter_is_rejected():
    with pytest.raises(ImproperlyConfigured, match="invalid converter"):
        _route_to_segments("items/<wat:id>/")


def test_invalid_parameter_name_is_rejected():
    """Parameter names must be valid Python identifiers."""
    with pytest.raises(ImproperlyConfigured, match="isn't a valid Python identifier"):
        _route_to_segments("items/<int:1abc>/")


def test_empty_parameter_name_is_rejected():
    """`<int:>` (no parameter name) — empty string isn't a valid identifier."""
    with pytest.raises(ImproperlyConfigured, match="isn't a valid Python identifier"):
        _route_to_segments("items/<int:>/")


def test_whitespace_in_brackets_is_rejected():
    with pytest.raises(ImproperlyConfigured, match="whitespace"):
        _route_to_segments("items/<int: id>/")


def test_mixed_segment_parses_as_pattern():
    """`prefix-<int:id>` mixes literal text with a converter in one segment —
    parses to a `Pattern` segment with literal + capture parts.
    """
    from plain.urls.segments import Pattern

    route = _route_to_segments("items/prefix-<int:id>")
    assert isinstance(route.segments[1], Pattern)
    assert route.segments[1].parts == (
        Literal(value="prefix-"),
        Capture(name="id", converter=INT),
    )


def test_suffix_capture_parses_as_pattern():
    """`<slug:slug>.js` — capture followed by literal suffix is the common case."""
    from plain.urls.segments import Pattern

    route = _route_to_segments("form/<slug:form_slug>.js")
    assert isinstance(route.segments[1], Pattern)


def test_multi_segment_capture_cannot_mix_with_literal():
    """`<path:rest>.js` — multi-segment converter mixed with literal text is rejected.
    Multi-segment captures span segment boundaries, which contradicts the
    within-segment match a Pattern uses.
    """
    with pytest.raises(ImproperlyConfigured, match="must occupy their own segment"):
        _route_to_segments("docs/<path:rest>.js")


def test_route_converters_accessor():
    route = _route_to_segments("users/<int:id>/posts/<slug:title>")
    converters = route.converters
    assert set(converters) == {"id", "title"}
    assert converters["id"] is INT


def test_include_prefix_parses_same_as_endpoint():
    """Include prefixes use the same parser; trailing_slash is captured
    but ignored by the matcher (include() always normalizes to `prefix/`)."""
    route = _route_to_segments("admin/")
    assert route.segments == (Literal(value="admin"),)
    assert route.trailing_slash is True


def test_consecutive_slashes_are_rejected():
    """`foo//bar` produces an empty segment that would never match anything
    at runtime — reject at registration so the dead route is obvious."""
    with pytest.raises(ImproperlyConfigured, match="empty segment"):
        _route_to_segments("foo//bar/")


def test_consecutive_slashes_inside_include_prefix_rejected():
    """Same check fires when an `include()` prefix slips a `//` through."""
    with pytest.raises(ImproperlyConfigured, match="empty segment"):
        _route_to_segments("a//b/")
