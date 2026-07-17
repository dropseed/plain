"""Contract tests for catchall route semantics.

A catchall is structurally a sole-segment terminal multi-segment
Capture (`path("<path:NAME>")`). Catchalls are slash-agnostic at match
time, yield to sibling `SlashMismatch`, and lose to specific matches.
The slash on the route string is irrelevant — `path("<path:_>/")` and
`path("<path:_>")` produce the same catchall route.
"""

from __future__ import annotations

from clients import catchall_client, included_catchall_client


def test_catchall_matches_unslashed_request():
    with catchall_client() as client:
        response = client.get("/missing")
        assert response.status_code == 404
        assert response.content == b"404: missing"


def test_catchall_matches_slashed_request_from_same_mount():
    with catchall_client() as client:
        response = client.get("/missing/")
        assert response.status_code == 404
        assert response.content == b"404: missing/"


def test_catchall_matches_multi_segment_path():
    with catchall_client() as client:
        response = client.get("/nested/deep/path")
        assert response.status_code == 404
        assert response.content == b"404: nested/deep/path"


def test_catchall_yields_to_specific_slash_mismatch():
    """Shadow-problem pin: without yield, the catchall would eat every
    trailing-slash redirect in the app."""
    with catchall_client() as client:
        response = client.get("/login")
        assert response.status_code == 308
        assert response.headers["Location"] == "/login/"


def test_specific_match_beats_catchall():
    with catchall_client() as client:
        response = client.get("/login/")
        assert response.status_code == 200
        assert response.content == b"login"


def test_catchall_does_not_match_root():
    with catchall_client() as client:
        response = client.get("/")
        assert response.status_code == 404
        assert response.headers["Content-Type"] == "text/plain; charset=utf-8"


def test_catchall_inside_include_still_yields_to_outer_slash_mismatch():
    """`include("", CatchallRouter)` after `path("login/")` — the catchall
    is two scopes down, but /login should still 308 to /login/. The
    `is_catchall` signal must survive include wrapping."""
    with included_catchall_client() as client:
        response = client.get("/login")
        assert response.status_code == 308
        assert response.headers["Location"] == "/login/"


def test_catchall_inside_include_still_fires_for_unmatched():
    with included_catchall_client() as client:
        response = client.get("/missing")
        assert response.status_code == 404
        assert response.content == b"404: missing"
