"""Contract tests for catchall route semantics.

`path("<path:NAME>")` (sole-segment terminal `<path:>`, no slash) is a
catchall: slash-agnostic, yields to sibling SlashMismatch, loses to
specific matches. The slashed form `path("<path:_>/")` is not.
"""

from __future__ import annotations


def test_catchall_matches_unslashed_request(catchall_client):
    response = catchall_client.get("/missing")
    assert response.status_code == 404
    assert response.content == b"404: missing"


def test_catchall_matches_slashed_request_from_same_mount(catchall_client):
    response = catchall_client.get("/missing/")
    assert response.status_code == 404
    assert response.content == b"404: missing/"


def test_catchall_matches_multi_segment_path(catchall_client):
    response = catchall_client.get("/nested/deep/path")
    assert response.status_code == 404
    assert response.content == b"404: nested/deep/path"


def test_catchall_yields_to_specific_slash_mismatch(catchall_client):
    """Shadow-problem pin: without yield, the catchall would eat every
    trailing-slash redirect in the app."""
    response = catchall_client.get("/login")
    assert response.status_code == 308
    assert response.headers["Location"] == "/login/"


def test_specific_match_beats_catchall(catchall_client):
    response = catchall_client.get("/login/")
    assert response.status_code == 200
    assert response.content == b"login"


def test_catchall_does_not_match_root(catchall_client):
    response = catchall_client.get("/")
    assert response.status_code == 404
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"


def test_slashed_catchall_is_not_a_catchall(slashed_catchall_client):
    response = slashed_catchall_client.get("/missing")
    assert response.status_code == 308
    assert response.headers["Location"] == "/missing/"

    response = slashed_catchall_client.get("/missing/")
    assert response.status_code == 404


def test_catchall_inside_include_still_yields_to_outer_slash_mismatch(
    included_catchall_client,
):
    """`include("", CatchallRouter)` after `path("login/")` — the catchall
    is two scopes down, but /login should still 308 to /login/. The
    `is_catchall` signal must survive include wrapping."""
    response = included_catchall_client.get("/login")
    assert response.status_code == 308
    assert response.headers["Location"] == "/login/"


def test_catchall_inside_include_still_fires_for_unmatched(
    included_catchall_client,
):
    response = included_catchall_client.get("/missing")
    assert response.status_code == 404
    assert response.content == b"404: missing"
