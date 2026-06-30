"""The 404-logging contract: repeat 404s for a URL collapse into one counted row.

Driven end-to-end through ``plain.test.Client`` — an unmatched path returns a
404, which is what the RedirectionMiddleware logs. Assertions cover only the
user-visible outcome: the HTTP status and the rows the middleware writes.
"""

from __future__ import annotations

from plain.redirection.models import NotFoundLog, Redirect, RedirectLog
from plain.test import Client


def make_client(**headers: str) -> Client:
    # A Host with a dot so the logged build_absolute_uri() is a valid URL
    # (the default "testserver" host fails URLField validation).
    return Client(headers={"Host": "example.com", **headers})


def test_unmatched_404_is_logged_once(db):
    response = make_client().get("/missing/")
    assert response.status_code == 404

    log = NotFoundLog.query.get()
    assert log.url.endswith("/missing/")
    assert log.count == 1
    assert log.first_seen == log.last_seen


def test_repeat_404s_increment_count_not_rows(db):
    client = make_client()
    client.get("/missing/")
    client.get("/missing/")
    client.get("/missing/")

    log = NotFoundLog.query.get()  # raises if there's more than one row
    assert log.url.endswith("/missing/")
    assert log.count == 3


def test_distinct_urls_get_separate_rows(db):
    client = make_client()
    client.get("/a/")
    client.get("/b/")
    client.get("/a/")

    assert NotFoundLog.query.count() == 2
    assert NotFoundLog.query.get(url__endswith="/a/").count == 2
    assert NotFoundLog.query.get(url__endswith="/b/").count == 1


def test_repeat_404_refreshes_last_seen_and_latest_metadata(db):
    make_client(**{"User-Agent": "first", "Referer": "ref-1"}).get("/missing/")
    make_client(**{"User-Agent": "second", "Referer": "ref-2"}).get("/missing/")

    log = NotFoundLog.query.get()
    assert log.count == 2
    assert log.last_seen >= log.first_seen
    # Metadata reflects the most recent hit, not the first.
    assert log.user_agent == "second"
    assert log.referrer == "ref-2"


def test_404_on_a_non_dotted_host_is_logged_not_an_error(db):
    # The default "testserver" host isn't a valid URL per URLField, so logging
    # such a request used to raise mid-response. url is a TextField now, so the
    # 404 is captured rather than turning into a 500.
    response = Client().get("/missing/")

    assert response.status_code == 404
    log = NotFoundLog.query.get()
    assert log.url.endswith("/missing/")
    assert log.count == 1


def test_matching_redirect_is_not_logged_as_a_404(db):
    Redirect.query.create(from_pattern="/old/", to_pattern="/new/", http_status=301)

    response = make_client().get("/old/")

    assert response.status_code == 301
    assert response.url.endswith("/new/")
    # A matched redirect is recorded as a redirect, never as a 404.
    assert NotFoundLog.query.count() == 0
    assert RedirectLog.query.count() == 1
