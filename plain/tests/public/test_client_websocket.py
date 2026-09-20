"""`Client.websocket()`: driving a view's `websocket()` from a test."""

from __future__ import annotations

import pytest
from plain.http import WebSocketClosed
from plain.test import Client, WebSocketRejected


def test_echo_round_trip_text_and_binary() -> None:
    with Client().websocket("/websocket/echo") as ws:
        ws.send("hello")
        assert ws.receive() == "hello"
        ws.send(b"\x00\x01\x02")
        assert ws.receive() == b"\x00\x01\x02"


def test_large_binary_message_does_not_deadlock() -> None:
    payload = bytes(range(256)) * 2048  # 512 KiB, well past any socket buffer
    with Client().websocket("/websocket/echo") as ws:
        ws.send(payload)
        assert ws.receive() == payload


def test_receive_times_out_when_the_view_is_silent() -> None:
    with Client().websocket("/websocket/sleeps") as ws, pytest.raises(TimeoutError):
        ws.receive(timeout=0.1)


def test_close_ends_the_view_iteration() -> None:
    ws = Client().websocket("/websocket/echo")
    with ws:
        ws.send("one")
        assert ws.receive() == "one"
        ws.close()


def test_close_against_a_view_that_never_reads_does_not_hang() -> None:
    with Client().websocket("/websocket/sleeps") as ws:
        ws.close(timeout=0.2)


def test_rejection_carries_the_response() -> None:
    with pytest.raises(WebSocketRejected) as excinfo:
        Client().websocket("/websocket/forbidden")
    assert excinfo.value.response.status_code == 403


def test_subprotocol_is_negotiated() -> None:
    with Client().websocket("/websocket/echo", subprotocols=("rfb", "binary")) as ws:
        assert ws.subprotocol == "binary"
        assert ws.response.headers["Sec-WebSocket-Protocol"] == "binary"


def test_view_exception_surfaces_from_receive_and_on_exit() -> None:
    ws = Client().websocket("/websocket/raises")
    with pytest.raises(RuntimeError, match="websocket view boom"):
        ws.receive()
    with pytest.raises(RuntimeError, match="websocket view boom"), ws:
        pass


def test_client_close_ends_a_view_that_keeps_talking() -> None:
    with Client().websocket("/websocket/talks") as ws:
        # The view iterates until we close, then tries to send; from our
        # side the next receive sees the closing handshake.
        ws.close()
        with pytest.raises(WebSocketClosed):
            ws.receive()


def test_view_closing_the_socket_raises_websocket_closed_on_receive() -> None:
    with Client().websocket("/websocket/closes") as ws:
        assert ws.receive() == "bye"
        with pytest.raises(WebSocketClosed) as excinfo:
            ws.receive()
        assert (excinfo.value.code, excinfo.value.reason) == (4000, "done here")
