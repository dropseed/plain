"""Running an accepted WebSocket over a connection.

Protocol-agnostic core shared by the h1 server (after it has framed the
101) and the test client (over a socketpair): start the `WebSocket`,
run the view's `websocket()` coroutine in the request's context, and
finish cleanly whichever way it ends — the view returning, the peer
leaving, the view failing, or the worker shutting down.
"""

import asyncio
import contextvars
from collections.abc import Callable
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.semconv.attributes import (
    client_attributes,
    error_attributes,
    http_attributes,
    url_attributes,
)
from plain.http import Request, WebSocket, WebSocketClosed, WebSocketResponse
from plain.http.websocket import WebSocketTransport
from plain.http.websocket_frames import CLOSE_GOING_AWAY, CLOSE_INTERNAL_ERROR
from plain.logs import log_exception
from plain.utils.otel import format_exception_type

from ..connection import is_client_socket_noise

tracer = trace.get_tracer("plain")

# How long a view gets to notice the socket ended on its own before it is
# cancelled. Iteration ends and `send` raises at once; this covers a view
# awaiting something else that will only look at `ws` afterwards.
VIEW_GRACE = 1.0


def is_normal_ending(exc: BaseException) -> bool:
    """A socket ending that is nobody's error: the peer left."""
    if isinstance(exc, WebSocketClosed):
        return True
    return isinstance(exc, OSError) and is_client_socket_noise(exc)


async def run_websocket(
    ws_response: WebSocketResponse,
    transport: WebSocketTransport,
    *,
    shutdown_wait: asyncio.Future[Any],
    close_timeout: Callable[[], float],
) -> BaseException | None:
    """Serve one accepted websocket to completion.

    `transport` is anything with `recv(n)`, `sendall(bytes)` and
    `close()` — the server's `Connection`, or the test client's adapter.
    Exactly one task, the view's coroutine, runs in the request's context
    (`ws_response.request_context`, set by the handler; a copy of the
    current context when nothing set it). `shutdown_wait` completes when the
    worker begins draining, at which point the peer gets a 1001 and the
    view task is cancelled. `close_timeout` is read at close time because
    the drain deadline is published after the socket opened.

    Returns the view's exception when it failed with something other than
    a normal ending, after logging it; `None` otherwise. The server drops
    the return value (the log is the record); the test client re-raises it
    so a failing view fails the test.
    """
    request = ws_response.request
    context = ws_response.request_context or contextvars.copy_context()
    ws = WebSocket(
        transport,
        subprotocol=ws_response.subprotocol,
        max_message_size=ws_response.max_message_size,
    )

    span = _start_socket_span(request, context)
    # Make the socket span current inside the request context so spans the
    # view emits nest under it (the handshake span in that context has
    # already ended).
    context.run(otel_context.attach, trace.set_span_in_context(span))

    error: BaseException | None = None
    view_task: asyncio.Task[None] | None = None
    try:
        async with ws:
            loop = asyncio.get_running_loop()
            view_task = loop.create_task(ws_response.handler(ws), context=context)
            socket_over = loop.create_task(ws.wait_closed())
            try:
                done, _ = await asyncio.wait(
                    {view_task, shutdown_wait, socket_over},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                socket_over.cancel()

            if view_task not in done:
                if shutdown_wait in done:
                    # Worker draining: tell the peer to reconnect elsewhere.
                    # Clients treat 1001 as "try again".
                    await ws.close(
                        CLOSE_GOING_AWAY,
                        "Server shutting down",
                        timeout=close_timeout(),
                    )
                else:
                    # The socket ended (the peer left, a ping went
                    # unanswered) while the view was waiting on something
                    # else. Give it a moment to notice — `async for` ends,
                    # `send` raises — then stop it.
                    await asyncio.wait(
                        {view_task}, timeout=min(VIEW_GRACE, close_timeout())
                    )
                if not view_task.done():
                    view_task.cancel()
                    await asyncio.wait({view_task})

            exc = None if view_task.cancelled() else view_task.exception()
            if exc is not None and not is_normal_ending(exc):
                error = exc
                span.set_status(trace.StatusCode.ERROR)
                span.set_attribute(
                    error_attributes.ERROR_TYPE, format_exception_type(exc)
                )
                span.record_exception(exc)
                with trace.use_span(span, end_on_exit=False):
                    log_exception(request, exc)  # ty: ignore[invalid-argument-type]
                await ws.close(
                    CLOSE_INTERNAL_ERROR, "Internal error", timeout=close_timeout()
                )
            else:
                await ws.close(timeout=close_timeout())
    finally:
        # However we got here — including being cancelled at the drain
        # deadline — the view must not outlive the socket, and the
        # closers below must not run under a live view.
        if view_task is not None and not view_task.done():
            view_task.cancel()
            await asyncio.gather(view_task, return_exceptions=True)
        span.end()
        # The resource closers registered on the accept — the request
        # body, the database connection — run now, as for any streaming
        # response once its body is done.
        ws_response.close()
    return error


def _start_socket_span(request: Request, context: contextvars.Context) -> trace.Span:
    """One SERVER span for the socket's life, a root linked to the handshake.

    A child of the handshake span would be an hour-long child of a
    ten-millisecond parent; a root with a link keeps both readable and
    still lets a failure inside the socket be attributed to an entry span.
    """
    handshake_span = context.run(trace.get_current_span)
    handshake_context = handshake_span.get_span_context()
    links = [trace.Link(handshake_context)] if handshake_context.is_valid else []

    route = request.resolver_match.route if request.resolver_match else None
    attributes: dict[str, Any] = {
        "plain.request.id": request.unique_id,
        http_attributes.HTTP_REQUEST_METHOD: "GET",
        http_attributes.HTTP_RESPONSE_STATUS_CODE: 101,
        url_attributes.URL_PATH: request.path,
        url_attributes.URL_SCHEME: request.scheme,
    }
    if route is not None:
        attributes[http_attributes.HTTP_ROUTE] = f"/{route}"
    if client_ip := request.client_ip:
        attributes[client_attributes.CLIENT_ADDRESS] = client_ip

    name = f"WEBSOCKET /{route}" if route is not None else "WEBSOCKET"
    return tracer.start_span(
        name, kind=trace.SpanKind.SERVER, links=links, attributes=attributes
    )
