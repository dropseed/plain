"""Unit tests for `_parse_path` — the request-path normalizer.

Direct unit tests because the function is the single source of truth for
what shape a path reaches the resolver in. End-to-end tests via the
`Client` go through `urllib.parse.urlparse`, which strips leading
double-slashes before the framework sees them — so the only way to
exercise the parser's handling of `//foo/` is to call it directly.
"""

from __future__ import annotations

from plain.test import cases
from plain.urls.paths import (
    BadPath,
    ParsedPath,
    RedirectToCanonical,
    _parse_path,
)


def test_root_is_canonical():
    result = _parse_path("/")
    assert result == ParsedPath(segments=(), trailing_slash=False)


def test_single_segment_no_slash():
    result = _parse_path("/users")
    assert result == ParsedPath(segments=("users",), trailing_slash=False)


def test_single_segment_with_trailing_slash():
    result = _parse_path("/users/")
    assert result == ParsedPath(segments=("users",), trailing_slash=True)


def test_multiple_segments():
    result = _parse_path("/users/42/posts/")
    assert result == ParsedPath(segments=("users", "42", "posts"), trailing_slash=True)


def test_leading_double_slash_redirects():
    result = _parse_path("//foo/")
    assert result == RedirectToCanonical(canonical="/foo/")


def test_middle_double_slash_redirects():
    result = _parse_path("/foo//bar/")
    assert result == RedirectToCanonical(canonical="/foo/bar/")


def test_trailing_double_slash_redirects():
    result = _parse_path("/foo//")
    assert result == RedirectToCanonical(canonical="/foo/")


def test_triple_slash_at_root_redirects_to_root():
    result = _parse_path("///")
    assert result == RedirectToCanonical(canonical="/")


def test_dot_in_middle_redirects():
    result = _parse_path("/foo/./bar")
    assert result == RedirectToCanonical(canonical="/foo/bar")


def test_dot_at_end_redirects_to_directory_form():
    result = _parse_path("/foo/.")
    assert result == RedirectToCanonical(canonical="/foo/")


def test_dotdot_pops_previous_segment():
    result = _parse_path("/foo/../bar")
    assert result == RedirectToCanonical(canonical="/bar")


def test_dotdot_at_end_redirects_to_directory_form():
    result = _parse_path("/foo/..")
    assert result == RedirectToCanonical(canonical="/")


@cases(
    "/..",  # bare `..` at root
    "/foo/../..",  # second `..` would pop below root
    "/../foo",  # `..` before anything else
)
def test_dotdot_below_root_is_bad_path(path):
    """Any `..` that would resolve below the URL root is rejected as 400."""
    assert isinstance(_parse_path(path), BadPath)


def test_percent_encoded_dots_are_literal_segments():
    """`_parse_path` doesn't decode percent-encoding. `%2e%2e` is a literal
    segment, NOT a dot segment — the framework treats WSGI/ASGI path decoding
    as the spec layer's job.
    """
    result = _parse_path("/foo/%2e%2e/bar")
    assert result == ParsedPath(segments=("foo", "%2e%2e", "bar"), trailing_slash=False)


def test_combined_normalizations_collapse():
    """`/foo//./bar/..` — empty segment collapses, `.` drops, `..` pops `bar`.
    Result: `/foo/` (with trailing slash from the `..` directory semantics).
    """
    result = _parse_path("/foo//./bar/..")
    assert result == RedirectToCanonical(canonical="/foo/")


def test_path_without_leading_slash_is_bad():
    """Request paths must start with `/`. (In practice, the HTTP layer
    guarantees this, but the parser defends against the invariant.)"""
    result = _parse_path("foo/bar")
    assert isinstance(result, BadPath)


def test_canonical_paths_round_trip():
    """ParsedPath outputs always reflect a path that wouldn't itself
    trigger another redirect."""
    for path in ["/", "/a", "/a/", "/a/b", "/a/b/", "/a/b/c/d/e/"]:
        result = _parse_path(path)
        assert isinstance(result, ParsedPath), f"{path} should parse cleanly"
        # Reconstruct the canonical form from segments + flag.
        if not result.segments:
            canonical = "/"
        else:
            canonical = "/" + "/".join(result.segments)
            if result.trailing_slash:
                canonical += "/"
        assert canonical == path
