"""HTTP middleware that manages the per-request database connection lifecycle."""

from functools import partial

from plain.http import HttpMiddleware, Response
from plain.http.request import Request

from .db import get_connection, return_database_connection


class DatabaseConnectionMiddleware(HttpMiddleware):
    """Returns the per-request DB connection to the pool at request end.

    Every response gets a closer that returns the request's connection
    wrapper when the response is closed. The wrapper is created here if
    the request never touched the database: it is lazy (no pool checkout
    until first use, and returning an unused one is a no-op), and creating
    it now, on the request context, means every task or thread that later
    runs from a copy of that context shares the one wrapper the closer
    knows about. The response is closed inside the request context once
    its body is sent, but the closer is still handed the wrapper
    explicitly, so returning it doesn't depend on which context a close
    runs in.

    A non-streaming response also returns the connection right now:
    the view is done with it. A streaming response keeps it until the
    body is drained — otherwise a generator that lazily queries (e.g.
    `Model.query.iterator()` inside a `StreamingResponse`) would see its
    cursor invalidated when the pool rolls back the returned connection.
    A websocket accept is not streaming — no view code has run when this
    sees it — so its handshake connection goes back to the pool before the
    socket starts, the wrapper re-acquires on the first query inside the
    socket if there is one, and the closer returns that when the socket
    ends. A viewer holding a socket open for an hour holds no database
    connection with it.
    """

    def after_response(self, request: Request, response: Response) -> Response:
        conn = get_connection()
        response._resource_closers.append(partial(return_database_connection, conn))
        if not response.streaming:
            return_database_connection(conn)
        return response
