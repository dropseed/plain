"""Contract tests for trailing-slash redirect behavior.

These tests pin **current** behavior of `RedirectSlashMiddleware`. The
URL routing arc plans to flip several of these assertions in a single,
visible commit:

- 301 → 308 (preserves POST method, cacheable)
- One-way (append-only) → bidirectional (also strip when route has no slash)
- `APPEND_SLASH` setting removed; route definition becomes source of truth
- POST-without-slash `RuntimeError` deleted (308 makes it unnecessary)

When that future lands, this file's diff is the user-facing changelog.
"""

from __future__ import annotations

from plain.runtime import settings


def test_slash_route_with_slash_matches(slash_client):
    response = slash_client.get("/with-slash/")
    assert response.status_code == 200
    assert response.content == b"with-slash GET"


def test_slash_route_without_slash_redirects_301(slash_client):
    """`path("with-slash/")` + request to `/with-slash` → 301 append redirect.

    Step #2 flips this to 308.
    """
    response = slash_client.get("/with-slash")
    assert response.status_code == 301
    assert response.headers["Location"] == "/with-slash/"


def test_noslash_route_without_slash_matches(slash_client):
    response = slash_client.get("/without-slash")
    assert response.status_code == 200
    assert response.content == b"without-slash GET"


def test_noslash_route_with_slash_404s(slash_client):
    """`path("without-slash")` + request to `/without-slash/` → 404.

    Today the redirect is one-way (append only). Step #2 makes this a 308
    redirect back to `/without-slash`.
    """
    response = slash_client.get("/without-slash/")
    assert response.status_code == 404


def test_append_slash_false_disables_redirect(slash_client):
    """With `APPEND_SLASH=False`, no redirect — `/with-slash` 404s.

    Step #2 removes `APPEND_SLASH` entirely; the route definition controls
    canonical form.
    """
    original = settings.APPEND_SLASH
    settings.APPEND_SLASH = False
    try:
        response = slash_client.get("/with-slash")
        assert response.status_code == 404
        # The canonical form still works.
        response = slash_client.get("/with-slash/")
        assert response.status_code == 200
    finally:
        settings.APPEND_SLASH = original


def test_nondebug_post_without_slash_silently_redirects(slash_client):
    """DEBUG=False + POST without slash → 301, body lost.

    The current bug step #2 fixes. Pinning so the flip to 308 is visible.
    """
    response = slash_client.post("/with-slash", data={"key": "val"})
    assert response.status_code == 301
    assert response.headers["Location"] == "/with-slash/"


def test_post_body_is_lost_across_301_redirect(slash_client):
    """Following the 301 turns the POST into a GET — the body never reaches the view.

    Demonstrates the actual user-visible bug step #2 fixes: 301 is *not*
    method-preserving, so a POST without trailing slash gets silently
    downgraded to GET and the body is discarded. Step #2 uses 308 (which
    preserves the method), and after that the final request to the view
    is still a POST with the original body intact.
    """
    response = slash_client.post("/with-slash", data={"key": "val"}, follow=True)
    assert response.redirect_chain == [("/with-slash/", 301)]
    assert response.request.method == "GET"
    assert response.content == b"with-slash GET"


def test_both_slash_forms_explicit_no_redirect(slash_client):
    """When both `path("dual/")` and `path("dual")` are defined, each form
    resolves to its own view with no redirect. The redirect middleware
    must not interfere when the requested form already matches a route.
    """
    response = slash_client.get("/dual/")
    assert response.status_code == 200
    assert response.content == b"dual with slash"

    response = slash_client.get("/dual")
    assert response.status_code == 200
    assert response.content == b"dual without slash"


def test_redirect_preserves_query_string(slash_client):
    """The append-slash redirect must carry the query string through.

    Step #2 will flip the status code to 308; the query-string preservation
    is what we're pinning here.
    """
    response = slash_client.get("/with-slash?foo=bar&baz=qux")
    assert response.status_code == 301
    assert response.headers["Location"] == "/with-slash/?foo=bar&baz=qux"


def test_redirect_works_for_parameterized_route(slash_client):
    """`path("items/<int:id>/")` + request to `/items/42` → redirect to
    `/items/42/`. The converter-matched segment must survive the redirect.
    """
    response = slash_client.get("/items/42")
    assert response.status_code == 301
    assert response.headers["Location"] == "/items/42/"


def test_suffix_does_not_trigger_redirect(slash_client):
    """`/with-slash.json` is a different URL from `/with-slash/`. The redirect
    logic must not bridge the gap by stripping/munging arbitrary suffixes —
    it should fall through to a normal 404.
    """
    response = slash_client.get("/with-slash.json")
    assert response.status_code == 404
