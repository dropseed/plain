from __future__ import annotations

from plain.http import WebSocket
from plain.templates.views import TemplateView
from plain.views import View


class WebSocketDemoView(TemplateView):
    """The demo page and its socket, on one URL: `get()` renders, `websocket()` echoes."""

    template_name = "websocket.html"
    websocket_subprotocols = ("echo",)

    async def websocket(self, ws: WebSocket) -> None:
        async for message in ws:
            await ws.send(message)


class EchoWebSocketView(View):
    """A bare echo for the conformance tools (`tools/ws-worker-test`,
    `tools/autobahn-wstest`), which send messages up to 16 MiB — hence
    the raised cap."""

    websocket_max_message_size = 16 * 1024 * 1024

    async def websocket(self, ws: WebSocket) -> None:
        async for message in ws:
            await ws.send(message)
