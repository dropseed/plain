"""Contract tests for trailing-slash redirect behavior.

The app-wide `URLS_TRAILING_SLASH` setting decides the canonical slash
form for every route that doesn't explicitly opt out via
`path(..., force_trailing_slash=True|False)`. Requests at the
non-canonical form 308-redirect to the canonical one (308 is used so
the HTTP method survives the round trip, and so browsers cache the
redirect).

The `slash_client` fixture pins `URLS_TRAILING_SLASH=True` so the
slashed assertions in this file are stable; the new-default (False)
behavior is exercised by dedicated tests below.
"""

from __future__ import annotations

import pytest

from plain.http import Response
from plain.runtime import settings
from plain.test import Client
from plain.urls import Router, path
from plain.urls.resolvers import _get_cached_resolver
from plain.views import View


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


def test_slash_redirect_preserves_opaque_captured_value(slash_client):
    """`/items/001` (no slash) on `path("items/<int:id>/", ...)` must 308 to
    `/items/001/`, not `/items/1/`.

    The slash redirect's job is to canonicalize the slash form, not to
    normalize captured values. INT's `to_url(to_python("001")) == "1"`
    would otherwise silently collapse leading zeros on every such
    redirect — opaque URL components should round-trip unchanged.
    """
    response = slash_client.get("/items/001")
    assert response.status_code == 308
    assert response.headers["Location"] == "/items/001/"


def test_suffix_does_not_trigger_redirect(slash_client):
    """`/with-slash.json` is a different URL from `/with-slash/`. The redirect
    logic must not bridge the gap by stripping/munging arbitrary suffixes —
    it should fall through to a normal 404.
    """
    response = slash_client.get("/with-slash.json")
    assert response.status_code == 404


def test_redirect_percent_encodes_captured_value(slash_client):
    """A captured value containing reserved characters must be percent-
    encoded in the Location header — otherwise a literal space, `?`, or
    `#` from the captured value would corrupt the URL.

    The test client passes the raw path through verbatim, so the
    captured `title` is the literal string `hello world` (with a real
    space). The 308 builder must percent-encode that before putting it
    in `Location`, otherwise the URL would be invalid.
    """
    response = slash_client.get("/notes/hello world")
    assert response.status_code == 308
    assert response.headers["Location"] == "/notes/hello%20world/"


def test_path_converter_obeys_route_trailing_slash(slash_client):
    """A `<path:...>` route's trailing-slash flag still drives the canonical
    form — the multi-segment capture doesn't absorb the slash. `slash_router`
    defines `path("docs/<path:rest>", DocsView)` (no slash); a request to
    `/docs/a/b/c/` 308s to `/docs/a/b/c`.
    """
    response = slash_client.get("/docs/a/b/c/")
    assert response.status_code == 308
    assert response.headers["Location"] == "/docs/a/b/c"

    response = slash_client.get("/docs/a/b/c")
    assert response.status_code == 200
    assert response.content == b"docs a/b/c"


def test_path_converter_requires_at_least_one_segment(slash_client):
    """`path("docs/<path:rest>", ...)` — the `<path:...>` capture's regex
    is `.+`, so the converter requires at least one remaining segment.
    Requests to the bare prefix `/docs` (or `/docs/`) must fall through
    to 404 rather than silently matching with `rest=""`.

    Pinning this so a future tweak to `_walk_segments`' multi-segment
    branch — e.g. allowing empty `"/".join(())` through — surfaces as a
    test failure instead of a silent reachability change for the prefix.
    """
    response = slash_client.get("/docs")
    assert response.status_code == 404

    response = slash_client.get("/docs/")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# URLS_TRAILING_SLASH and force_trailing_slash semantics
# ---------------------------------------------------------------------------


class _OkView(View):
    def get(self):
        return Response("ok")


@pytest.fixture
def setting_client(request):
    """Install a Router class as `URLS_ROUTER` plus a chosen
    `URLS_TRAILING_SLASH`, yield a Client. Tests use this to exercise
    the global setting + per-route override combinations."""

    def _make(router_cls: type[Router], *, urls_trailing_slash: bool) -> Client:
        attr = f"_TrailingSlashRouter_{request.node.name}"
        request.module.__dict__[attr] = router_cls
        request.addfinalizer(lambda: request.module.__dict__.pop(attr, None))

        original_router = settings.URLS_ROUTER
        original_ts = settings.URLS_TRAILING_SLASH
        request.addfinalizer(lambda: setattr(settings, "URLS_ROUTER", original_router))
        request.addfinalizer(
            lambda: setattr(settings, "URLS_TRAILING_SLASH", original_ts)
        )
        request.addfinalizer(_get_cached_resolver.cache_clear)

        settings.URLS_ROUTER = f"{request.module.__name__}.{attr}"
        settings.URLS_TRAILING_SLASH = urls_trailing_slash
        _get_cached_resolver.cache_clear()

        client = Client(raise_request_exception=False)
        client.handler._middleware_chain = None
        client.handler.load_middleware()
        return client

    return _make


def test_global_setting_false_serves_no_slash(setting_client):
    """With `URLS_TRAILING_SLASH=False`, `path("home")` (or `"home/"`,
    they're identical) serves `/home`. The slashed request redirects."""

    class _R(Router):
        namespace = ""
        urls = [path("home", _OkView, name="home")]

    client = setting_client(_R, urls_trailing_slash=False)
    assert client.get("/home").status_code == 200
    response = client.get("/home/")
    assert response.status_code == 308
    assert response.headers["Location"] == "/home"


def test_global_setting_true_serves_slash(setting_client):
    """With `URLS_TRAILING_SLASH=True`, the same route serves `/home/`."""

    class _R(Router):
        namespace = ""
        urls = [path("home", _OkView, name="home")]

    client = setting_client(_R, urls_trailing_slash=True)
    assert client.get("/home/").status_code == 200
    response = client.get("/home")
    assert response.status_code == 308
    assert response.headers["Location"] == "/home/"


def test_route_string_slash_is_irrelevant(setting_client):
    """`path("home/")` and `path("home")` produce identical routes —
    the slash in the string is stripped silently."""

    class _R(Router):
        namespace = ""
        urls = [path("home/", _OkView, name="home")]

    client = setting_client(_R, urls_trailing_slash=False)
    assert client.get("/home").status_code == 200
    assert client.get("/home/").status_code == 308


def test_force_trailing_slash_true_overrides_global_false(setting_client):
    """Under `URLS_TRAILING_SLASH=False`, a route with
    `force_trailing_slash=True` still has a trailing slash."""

    class _R(Router):
        namespace = ""
        urls = [
            path("home", _OkView, name="home", force_trailing_slash=True),
        ]

    client = setting_client(_R, urls_trailing_slash=False)
    assert client.get("/home/").status_code == 200
    response = client.get("/home")
    assert response.status_code == 308
    assert response.headers["Location"] == "/home/"


def test_force_trailing_slash_false_overrides_global_true(setting_client):
    """Under `URLS_TRAILING_SLASH=True`, a route with
    `force_trailing_slash=False` has no trailing slash. Useful for
    file-extension routes (`sitemap.xml`, `robots.txt`) under a
    slash-by-default app."""

    class _R(Router):
        namespace = ""
        urls = [
            path(
                "sitemap.xml",
                _OkView,
                name="sitemap",
                force_trailing_slash=False,
            ),
        ]

    client = setting_client(_R, urls_trailing_slash=True)
    assert client.get("/sitemap.xml").status_code == 200
    response = client.get("/sitemap.xml/")
    assert response.status_code == 308
    assert response.headers["Location"] == "/sitemap.xml"


def test_root_route_is_slash_neutral_under_global_true(setting_client):
    """`path("", HomeView)` is reachable only at `/`. Under
    `URLS_TRAILING_SLASH=True` a naive `trailing_slash=True` reading
    would force `/` to 308-redirect (toggling to the empty path),
    breaking the home page. Root routes ignore the global setting."""

    class _R(Router):
        namespace = ""
        urls = [path("", _OkView, name="home")]

    client = setting_client(_R, urls_trailing_slash=True)
    response = client.get("/")
    assert response.status_code == 200
    assert response.content == b"ok"


def test_root_route_is_slash_neutral_under_global_false(setting_client):
    """Same root invariant under `URLS_TRAILING_SLASH=False`."""

    class _R(Router):
        namespace = ""
        urls = [path("", _OkView, name="home")]

    client = setting_client(_R, urls_trailing_slash=False)
    response = client.get("/")
    assert response.status_code == 200
    assert response.content == b"ok"
