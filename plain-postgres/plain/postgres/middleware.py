"""HTTP middleware that manages the per-request database connection lifecycle."""

from __future__ import annotations

from functools import partial

from plain.http import HttpMiddleware, Response
from plain.http.request import Request

from .db import _db_conn, return_database_connection


class DatabaseConnectionMiddleware(HttpMiddleware):
    """Returns the per-request DB connection to the pool at request end.

    For streaming responses the connection is returned when the body is
    fully drained (via `_resource_closers`) rather than when the view
    returns — otherwise generators that lazily query the DB (e.g.
    `Model.query.iterator()` inside a `StreamingResponse`) would see their
    cursor invalidated when the pool rolls back the returned connection.

    The streaming path captures the wrapper *now* and hands it to the
    closer explicitly, because `response.close()` runs after `handle()`
    returns — outside the per-request `contextvars.Context` — so a
    `_db_conn.get()` at close time would miss the wrapper entirely.
    """

    def after_response(self, request: Request, response: Response) -> Response:
        if response.streaming:
            conn = _db_conn.get()
            if conn is not None:
                response._resource_closers.append(
                    partial(return_database_connection, conn)
                )
        else:
            return_database_connection()
        return response
