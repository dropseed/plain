"""Contract tests for trailing-slash redirect behavior.

The route definition is the source of truth for the canonical URL:

- `path("users/", V)` → canonical form is `/users/`; `/users` 308-redirects to `/users/`.
- `path("users", V)` → canonical form is `/users`; `/users/` 308-redirects to `/users`.

308 is used because it preserves the HTTP method (POST stays POST) and is
cacheable, so browsers learn the redirect after one round trip.
"""

from __future__ import annotations


def test_slash_route_with_slash_matches(slash_client):
    response = slash_client.get("/with-slash/")
    assert response.status_code == 200
    assert response.content == b"with-slash GET"


def test_slash_route_without_slash_redirects(slash_client):
    """`path("with-slash/")` + request to `/with-slash` → 308 append redirect."""
    response = slash_client.get("/with-slash")
    assert response.status_code == 308
    assert response.headers["Location"] == "/with-slash/"


def test_noslash_route_without_slash_matches(slash_client):
    response = slash_client.get("/without-slash")
    assert response.status_code == 200
    assert response.content == b"without-slash GET"


def test_noslash_route_with_slash_redirects(slash_client):
    """`path("without-slash")` + request to `/without-slash/` → 308 strip redirect."""
    response = slash_client.get("/without-slash/")
    assert response.status_code == 308
    assert response.headers["Location"] == "/without-slash"


def test_post_method_preserved_across_redirect(slash_client):
    """POST to non-canonical form survives the 308 — method and body preserved."""
    response = slash_client.post("/with-slash", data={"key": "val"}, follow=True)
    assert response.redirect_chain == [("/with-slash/", 308)]
    assert response.request.method == "POST"
    assert response.content == b"with-slash POST"


def test_post_method_preserved_without_body(slash_client):
    """POST with no body follows the 308 with the same body shape (empty
    multipart form) and content headers as the initial request — not `b""`.
    """
    response = slash_client.post("/with-slash", follow=True)
    assert response.redirect_chain == [("/with-slash/", 308)]
    assert response.request.method == "POST"
    assert response.content == b"with-slash POST"
    # 308 must preserve the body shape: the followed request carries the
    # same empty-multipart body and content headers as the initial request.
    assert response.request.headers.get("Content-Type", "").startswith(
        "multipart/form-data"
    )


def test_both_slash_forms_explicit_no_redirect(slash_client):
    """When both `path("dual/")` and `path("dual")` are defined, each form
    resolves to its own view with no redirect interference.
    """
    response = slash_client.get("/dual/")
    assert response.status_code == 200
    assert response.content == b"dual with slash"

    response = slash_client.get("/dual")
    assert response.status_code == 200
    assert response.content == b"dual without slash"


def test_redirect_preserves_query_string(slash_client):
    """The redirect must carry the query string through verbatim."""
    response = slash_client.get("/with-slash?foo=bar&baz=qux")
    assert response.status_code == 308
    assert response.headers["Location"] == "/with-slash/?foo=bar&baz=qux"


def test_followed_redirect_preserves_query_string(slash_client):
    """Following the 308 must land at the canonical URL with the original query
    string intact — i.e. the test client honors `Location`'s query string."""
    response = slash_client.get("/with-slash?foo=bar", follow=True)
    assert response.redirect_chain == [("/with-slash/?foo=bar", 308)]
    assert response.request.query_string == "foo=bar"


def test_redirect_works_for_parameterized_route(slash_client):
    """`path("items/<int:id>/")` + request to `/items/42` → 308 to `/items/42/`."""
    response = slash_client.get("/items/42")
    assert response.status_code == 308
    assert response.headers["Location"] == "/items/42/"


def test_suffix_does_not_trigger_redirect(slash_client):
    """`/with-slash.json` is a different URL from `/with-slash/`. The redirect
    logic must not bridge the gap by stripping/munging arbitrary suffixes —
    it should fall through to a normal 404.
    """
    response = slash_client.get("/with-slash.json")
    assert response.status_code == 404
