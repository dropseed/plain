"""End-to-end tests for database-driven redirects.

A request that would 404 is intercepted by RedirectionMiddleware, which
looks up an enabled Redirect, logs the hit, and issues the redirect. These
tests drive that through the real request/response cycle with ``Client``.
"""

from __future__ import annotations

from plain.redirection.models import NotFoundLog, Redirect, RedirectLog
from plain.test import Client

# The logs store absolute URLs in URLFields, so requests need a host that
# validates as a real domain (the "testserver" default does not).
HOST = {"Host": "example.com"}


def _get(path):
    return Client().get(path, headers=HOST)


def test_exact_redirect():
    Redirect.query.create(
        from_pattern="/old-page/",
        to_pattern="/new-page/",
        http_status=301,
    )

    response = _get("/old-page/")

    assert response.status_code == 301
    assert response.headers["Location"].endswith("/new-page/")


def test_redirect_status_code_is_respected():
    Redirect.query.create(
        from_pattern="/temp/",
        to_pattern="/somewhere/",
        http_status=302,
    )

    assert _get("/temp/").status_code == 302


def test_regex_redirect_substitutes_groups():
    Redirect.query.create(
        from_pattern=r"^/blog/(\d+)/$",
        to_pattern=r"/posts/\1/",
        http_status=301,
        is_regex=True,
    )

    response = _get("/blog/42/")

    assert response.status_code == 301
    assert response.headers["Location"].endswith("/posts/42/")


def test_disabled_redirect_is_ignored():
    Redirect.query.create(
        from_pattern="/disabled/",
        to_pattern="/nope/",
        enabled=False,
    )

    response = _get("/disabled/")

    assert response.status_code == 404
    # A disabled rule doesn't fire, so the miss is logged as a 404.
    assert NotFoundLog.query.filter(url__endswith="/disabled/").count() == 1


def test_successful_redirect_is_logged():
    redirect = Redirect.query.create(
        from_pattern="/logged/",
        to_pattern="/destination/",
    )

    _get("/logged/")

    log = RedirectLog.query.get(redirect=redirect)
    assert log.from_url.endswith("/logged/")
    assert log.to_url.endswith("/destination/")
    assert log.http_status == 301


def test_unmatched_404_is_logged_as_not_found():
    Redirect.query.create(from_pattern="/something/", to_pattern="/else/")

    response = _get("/no-rule-here/")

    assert response.status_code == 404
    assert NotFoundLog.query.filter(url__endswith="/no-rule-here/").count() == 1
    assert RedirectLog.query.count() == 0


def test_lower_order_redirect_wins():
    # Two distinct patterns both match /dup/x/; `order` breaks the tie
    # (lower runs first). from_pattern is unique, so the patterns differ.
    Redirect.query.create(
        from_pattern=r"^/dup/.*$", to_pattern="/broad/", is_regex=True, order=10
    )
    Redirect.query.create(
        from_pattern=r"^/dup/x/$", to_pattern="/specific/", is_regex=True, order=1
    )

    response = _get("/dup/x/")

    assert response.headers["Location"].endswith("/specific/")


def test_existing_page_is_not_redirected():
    Redirect.query.create(from_pattern="/", to_pattern="/elsewhere/")

    # "/" resolves to a real view, so the 404 path (and redirect) never runs.
    response = _get("/")

    assert response.status_code == 200
    assert response.content == b"home"
    assert RedirectLog.query.count() == 0
