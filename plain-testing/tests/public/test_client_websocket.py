"""`Client.websocket()`: driving a view's `websocket()` from a test."""

from plain.http import WebSocketClosed
from plain.testing import Client, WebSocketRejected, raises


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
    with Client().websocket("/websocket/sleeps") as ws, raises(TimeoutError):
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
    with raises(WebSocketRejected) as caught:
        Client().websocket("/websocket/forbidden")
    response = caught.exception.response
    assert response.status_code == 403
    assert response.request.path == "/websocket/forbidden"


def test_a_handshake_that_raises_raises_from_the_client() -> None:
    # As any other request the client makes does.
    with raises(RuntimeError, match="websocket handshake boom"):
        Client().websocket("/websocket/handshake-raises")


def test_a_handshake_that_raises_is_a_rejection_when_not_raising() -> None:
    client = Client(raise_exceptions=False)

    with raises(WebSocketRejected) as caught:
        client.websocket("/websocket/handshake-raises")

    response = caught.exception.response
    assert response.status_code == 500
    assert isinstance(response.exception, RuntimeError)


def test_subprotocol_is_negotiated() -> None:
    with Client().websocket("/websocket/echo", subprotocols=("rfb", "binary")) as ws:
        assert ws.subprotocol == "binary"
        assert ws.response.headers["Sec-WebSocket-Protocol"] == "binary"


def test_view_exception_surfaces_from_receive_and_on_exit() -> None:
    ws = Client().websocket("/websocket/raises")
    with raises(RuntimeError, match="websocket view boom"):
        ws.receive()
    with raises(RuntimeError, match="websocket view boom"), ws:
        pass


def test_client_close_ends_a_view_that_keeps_talking() -> None:
    with Client().websocket("/websocket/talks") as ws:
        # The view iterates until we close, then tries to send; from our
        # side the next receive sees the closing handshake.
        ws.close()
        with raises(WebSocketClosed):
            ws.receive()


def test_view_closing_the_socket_raises_websocket_closed_on_receive() -> None:
    with Client().websocket("/websocket/closes") as ws:
        assert ws.receive() == "bye"
        with raises(WebSocketClosed) as caught:
            ws.receive()
        assert (caught.exception.code, caught.exception.reason) == (4000, "done here")


def test_query_params_reach_the_handshake_request() -> None:
    with Client().websocket("/websocket/echo", query_params={"room": "7"}) as ws:
        assert ws.request.query_params["room"] == "7"
