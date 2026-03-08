"""WebSocket upgrade handling.

Detects WebSocket upgrades from HTTP/1.1, runs middleware and
authorization, performs the handshake, and manages the connection
lifecycle (connect → receive loop → disconnect).

Called from h1.handle_connection when an Upgrade header is detected.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .accesslog import log_access, log_websocket
from .connection import Connection
from .http.response import Response

if TYPE_CHECKING:
    from plain.http import Request as HttpRequest
    from plain.websockets import WebSocketHandler

    from .workers.worker import Worker

log = logging.getLogger("plain.server")


def is_websocket_upgrade(header_data: bytes) -> bool:
    """Quick check for WebSocket upgrade in raw header bytes.

    Called on every HTTP/1.1 request, so the fast path (non-WS) must
    be cheap: a single bytes.lower() + two substring checks.
    """
    lowered = header_data.lower()
    if b"upgrade" not in lowered or b"websocket" not in lowered:
        return False

    header_str = header_data.decode("latin-1")
    has_upgrade = False
    has_connection_upgrade = False
    for line in header_str.split("\r\n"):
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name_upper = name.strip().upper()
        if name_upper == "UPGRADE" and value.strip().lower() == "websocket":
            has_upgrade = True
        elif name_upper == "CONNECTION" and "upgrade" in value.lower():
            has_connection_upgrade = True
        if has_upgrade and has_connection_upgrade:
            return True
    return False


def resolve_websocket_handler(
    http_request: HttpRequest,
) -> type[WebSocketHandler] | None:
    """Check if the resolved URL maps to a WebSocketHandler subclass.

    Caches the resolver match on the request so dispatch() doesn't
    re-resolve the URL.
    """
    from plain.urls import get_resolver
    from plain.urls.exceptions import Resolver404
    from plain.websockets import WebSocketHandler

    try:
        resolver = get_resolver()
        match = resolver.resolve(http_request.path_info)
        http_request.resolver_match = match
        if issubclass(match.view_class, WebSocketHandler):
            return match.view_class
    except Resolver404:
        pass
    return None


async def _send_rejection(
    req: Any,
    conn: Connection,
    http_response: Any,
    request_start: datetime,
) -> bool:
    """Write an HTTP rejection response (before WebSocket upgrade) and log access."""
    resp = Response(req, conn.writer, is_ssl=conn.is_ssl)
    try:
        await resp.async_write_response(http_response)
    finally:
        request_time = datetime.now() - request_start
        if http_response.log_access:
            log_access(resp, req, request_time)
        if hasattr(http_response, "close"):
            http_response.close()

    if resp.should_close():
        return False
    return True


async def dispatch(
    worker: Worker,
    req: Any,
    conn: Connection,
    http_request: HttpRequest,
    request_start: datetime,
    ws_handler_class: type[WebSocketHandler],
) -> bool:
    """WebSocket dispatch: before_request middleware, authorize, then handoff."""
    from plain.http import ForbiddenError403
    from plain.internal.handlers.exception import response_for_exception

    loop = asyncio.get_running_loop()
    try:
        # Send request_started signal + run before_request middleware
        def _signal_and_before() -> tuple[Any, list[Any]]:
            from plain import signals

            signals.request_started.send(sender=worker.__class__, request=http_request)
            return worker.handler._run_before_request(http_request)

        response, ran_before = await loop.run_in_executor(
            worker.tpool, _signal_and_before
        )

        # If middleware short-circuited, send that response normally
        if response is not None:
            response = await loop.run_in_executor(
                worker.tpool,
                worker.handler._finish_pipeline,
                http_request,
                response,
                ran_before,
            )
            return await _send_rejection(req, conn, response, request_start)

        # Resolve URL kwargs and instantiate the handler
        match = worker.handler._resolve_request(http_request)
        ws_handler = ws_handler_class(
            request=http_request,
            url_kwargs=match.kwargs,
        )

        # Origin check (CSWSH prevention) then authorize
        if not ws_handler.check_origin():
            response = response_for_exception(
                http_request,
                ForbiddenError403(),
            )
            response = await loop.run_in_executor(
                worker.tpool,
                worker.handler._finish_pipeline,
                http_request,
                response,
                ran_before,
            )
            return await _send_rejection(req, conn, response, request_start)

        authorized = await ws_handler.authorize()
        if not authorized:
            response = response_for_exception(
                http_request,
                ForbiddenError403(),
            )
            response = await loop.run_in_executor(
                worker.tpool,
                worker.handler._finish_pipeline,
                http_request,
                response,
                ran_before,
            )
            return await _send_rejection(req, conn, response, request_start)

        # Hand off to WebSocket handler — no after_response middleware
        return await _handle_websocket(req, conn, ws_handler, request_start)
    except Exception:
        log.exception("Error during WebSocket dispatch")
        try:
            await conn.write_error(500, "Internal Server Error", "")
        except Exception:
            log.debug("Failed to send error response")
        return False


async def _handle_websocket(
    req: Any,
    conn: Connection,
    ws_handler: WebSocketHandler,
    request_start: datetime,
) -> bool:
    """Perform WebSocket handshake and run lifecycle."""
    from plain.server.protocols.websocket import (
        build_accept_response,
        validate_handshake_headers,
    )
    from plain.websockets import WebSocketConnection

    # Validate handshake from the original HTTP request headers
    headers = [(k, v) for k, v in ws_handler.request.headers.items()]
    handshake = validate_handshake_headers(headers)

    if not handshake.is_websocket or handshake.error:
        reason = handshake.error or "not upgrade"
        log.warning("Invalid WebSocket handshake: %s", reason)
        await conn.write_error(400, "Bad Request", reason)
        return False

    # Send 101 Switching Protocols
    await conn.sendall(
        build_accept_response(
            handshake.ws_key,
            permessage_deflate=handshake.permessage_deflate,
        )
    )

    # Create connection object with all config from the view.
    # conn.reader/writer are already asyncio streams (even for SSL,
    # since asyncio.start_server(ssl=...) handles TLS natively).
    ws = WebSocketConnection(
        conn.reader,
        conn.writer,
        send_timeout=ws_handler.send_timeout,
        max_message_size=ws_handler.max_message_size,
        ping_interval=ws_handler.ping_interval,
        permessage_deflate=handshake.permessage_deflate,
    )

    log_websocket(req, "connect")
    connected = False
    try:
        await ws_handler.connect(ws)
        connected = True
        ws.start_ping_loop()

        async for message in ws:
            await ws_handler.receive(ws, message)
    except Exception:
        log.exception("WebSocket error")
        await ws.close(1011, "Internal error")
    finally:
        await ws.stop_ping_loop()

        if connected:
            try:
                await ws_handler.disconnect(ws)
            except Exception:
                log.exception("Error in WebSocket disconnect")

        await ws.close_transport()

        request_time = datetime.now() - request_start
        log_websocket(req, "disconnect", request_time=request_time)

    return False  # no keepalive after WebSocket
