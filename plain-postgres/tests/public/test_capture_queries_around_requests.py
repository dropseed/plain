"""`capture_queries()` and `max_queries()` around a request the client makes.

With `DatabaseConnectionMiddleware` installed, a request returns its
connection when it ends, unless a transaction is open. A test in the usual
rolled-back transaction has one open. An `@isolated_db` test doesn't, and a
capture around its requests used to come back empty: `max_queries(0)` passed
however many queries the view ran.
"""

from collections.abc import Generator
from contextlib import contextmanager

from app.examples.models.relationships import Widget
from plain.http import Response
from plain.postgres.testing import capture_queries, isolated_db, max_queries
from plain.testing import Client, override_settings, raises
from plain.urls import Router, path
from plain.urls.resolvers import _get_cached_resolver
from plain.views import View


class ThreeQueriesView(View):
    def get(self):
        for _ in range(3):
            Widget.query.count()
        return Response("counted")


class RequestsRouter(Router):
    namespace = ""
    urls = (path("three-queries", ThreeQueriesView, name="three_queries"),)


@contextmanager
def app_with_the_database_middleware() -> Generator[None]:
    _get_cached_resolver.cache_clear()
    try:
        with override_settings(
            URLS_ROUTER=f"{__name__}.RequestsRouter",
            MIDDLEWARE=["plain.postgres.DatabaseConnectionMiddleware"],
        ):
            yield
    finally:
        _get_cached_resolver.cache_clear()


def counts(queries) -> list[str]:
    return [q for q in queries.sql_statements() if "COUNT" in q]


def test_a_request_inside_the_tests_transaction_is_captured():
    with app_with_the_database_middleware(), capture_queries() as queries:
        Client().get("/three-queries")

    assert len(counts(queries)) == 3


@isolated_db
def test_a_request_in_an_isolated_db_test_is_captured():
    with app_with_the_database_middleware(), capture_queries() as queries:
        Client().get("/three-queries")

    assert len(counts(queries)) == 3


@isolated_db
def test_two_requests_in_an_isolated_db_test_are_both_captured():
    with app_with_the_database_middleware(), capture_queries() as queries:
        client = Client()
        client.get("/three-queries")
        client.get("/three-queries")

    assert len(counts(queries)) == 6


@isolated_db
def test_a_query_budget_fails_in_an_isolated_db_test():
    with (
        app_with_the_database_middleware(),
        raises(AssertionError, match="Expected at most 0 queries"),
        max_queries(0),
    ):
        Client().get("/three-queries")
