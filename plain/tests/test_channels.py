"""Tests for the plain.channels infrastructure.

Tests are organized in three levels:
1. Unit tests — SSE formatting, channel registry (no infrastructure needed)
2. Integration tests — AsyncConnectionManager + SSEConnection with socket pairs (no Postgres)
3. Postgres integration — PostgresListener + full pipeline (needs DATABASE_URL)
"""

import asyncio
import os
import socket

import pytest

from plain.channels.channel import Channel
from plain.channels.registry import ChannelRegistry
from plain.channels.sse import SSE_HEADERS, format_sse_comment, format_sse_event


# ---------------------------------------------------------------------------
# Test channel for use in integration tests
# ---------------------------------------------------------------------------
class StubChannel(Channel):
    path = "/test-events/"

    def authorize(self, request):
        return True

    def subscribe(self, request):
        return ["test_chan"]

    def transform(self, channel_name, payload):
        return payload


# ===================================================================
# Level 1: Unit tests (no infrastructure)
# ===================================================================


class TestSSEFormatting:
    def test_format_event_simple(self):
        result = format_sse_event("hello")
        assert result == b"data: hello\n\n"

    def test_format_event_with_type(self):
        result = format_sse_event("hello", event="message")
        assert b"event: message\n" in result
        assert b"data: hello\n" in result

    def test_format_event_with_id(self):
        result = format_sse_event("hello", event_id="42")
        assert b"id: 42\n" in result

    def test_format_event_with_retry(self):
        result = format_sse_event("hello", retry=3000)
        assert b"retry: 3000\n" in result

    def test_format_event_dict_payload(self):
        result = format_sse_event({"key": "value"})
        assert b'data: {"key": "value"}\n\n' == result

    def test_format_event_multiline(self):
        result = format_sse_event("line1\nline2")
        assert b"data: line1\ndata: line2\n\n" == result

    def test_format_event_none_payload(self):
        result = format_sse_event(None)
        assert b"data: \n\n" == result

    def test_format_comment(self):
        result = format_sse_comment("heartbeat")
        assert result == b": heartbeat\n\n"

    def test_format_comment_empty(self):
        result = format_sse_comment()
        assert result == b": \n\n"

    def test_sse_headers(self):
        header_dict = dict(SSE_HEADERS)
        assert header_dict["Content-Type"] == "text/event-stream"
        assert header_dict["Cache-Control"] == "no-cache"
        assert header_dict["Connection"] == "keep-alive"


class TestChannelRegistry:
    def test_register_and_match(self):
        registry = ChannelRegistry()

        @registry.register
        class MyChannel(Channel):
            path = "/events/"

        assert registry.match("/events/") is not None
        assert registry.match("/events/").path == "/events/"

    def test_match_returns_none_for_unknown(self):
        registry = ChannelRegistry()
        assert registry.match("/unknown/") is None

    def test_register_requires_path(self):
        registry = ChannelRegistry()
        with pytest.raises(ValueError, match="must define a 'path'"):

            @registry.register
            class BadChannel(Channel):
                pass

    def test_get_all(self):
        registry = ChannelRegistry()

        @registry.register
        class Chan1(Channel):
            path = "/a/"

        @registry.register
        class Chan2(Channel):
            path = "/b/"

        all_channels = registry.get_all()
        assert len(all_channels) == 2
        assert "/a/" in all_channels
        assert "/b/" in all_channels


class TestChannelBaseClass:
    def test_default_authorize(self):
        ch = Channel()
        assert ch.authorize(None) is True

    def test_default_subscribe(self):
        ch = Channel()
        assert ch.subscribe(None) == []

    def test_default_transform(self):
        ch = Channel()
        assert ch.transform("chan", "payload") == "payload"


# ===================================================================
# Level 2: Integration tests — async pipeline with socket pairs
# ===================================================================


def _make_socket_pair():
    """Create a connected socket pair and return (server_fd_for_async, client_sock_for_reading).

    The returned fd is dup'd — the caller (SSEConnection) takes ownership.
    The client_sock should be used to read what the async side sends.
    """
    server_sock, client_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    dup_fd = os.dup(server_sock.fileno())
    server_sock.close()  # Close the original; async side owns the dup
    client_sock.setblocking(False)
    return dup_fd, client_sock


class TestSSEConnection:
    def test_open_sends_headers(self):
        """SSEConnection.open() should send HTTP 200 + SSE headers."""
        from plain.channels.handler import SSEConnection

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            conn = SSEConnection(fd, StubChannel(), ["test_chan"], loop)
            conn.open()

            # Read what was sent
            client.setblocking(True)
            client.settimeout(1.0)
            data = client.recv(4096)

            assert b"HTTP/1.1 200 OK" in data
            assert b"text/event-stream" in data
            assert b"Cache-Control: no-cache" in data

            conn.close()
        finally:
            client.close()
            loop.close()

    def test_send_event(self):
        """SSEConnection.send_event() should send formatted SSE data."""
        from plain.channels.handler import SSEConnection

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            conn = SSEConnection(fd, StubChannel(), ["test_chan"], loop)
            conn.open()

            # Drain the headers
            client.setblocking(True)
            client.settimeout(1.0)
            client.recv(4096)

            # Send an event
            result = loop.run_until_complete(conn.send_event("hello", event="msg"))
            assert result is True

            data = client.recv(4096)
            assert b"event: msg\n" in data
            assert b"data: hello\n" in data

            conn.close()
        finally:
            client.close()
            loop.close()

    def test_send_heartbeat(self):
        """SSEConnection.send_heartbeat() should send an SSE comment."""
        from plain.channels.handler import SSEConnection

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            conn = SSEConnection(fd, StubChannel(), ["test_chan"], loop)
            conn.open()

            client.setblocking(True)
            client.settimeout(1.0)
            client.recv(4096)  # drain headers

            result = loop.run_until_complete(conn.send_heartbeat())
            assert result is True

            data = client.recv(4096)
            assert b": heartbeat\n\n" in data

            conn.close()
        finally:
            client.close()
            loop.close()

    def test_send_to_closed_returns_false(self):
        """Sending to a closed connection should return False."""
        from plain.channels.handler import SSEConnection

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            conn = SSEConnection(fd, StubChannel(), ["test_chan"], loop)
            conn.open()
            conn.close()

            result = loop.run_until_complete(conn.send_event("hello"))
            assert result is False

            result = loop.run_until_complete(conn.send_heartbeat())
            assert result is False
        finally:
            client.close()
            loop.close()

    def test_send_to_broken_pipe_returns_false(self):
        """Sending after the client disconnects should return False."""
        from plain.channels.handler import SSEConnection

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            conn = SSEConnection(fd, StubChannel(), ["test_chan"], loop)
            conn.open()

            client.setblocking(True)
            client.settimeout(1.0)
            client.recv(4096)  # drain headers

            # Close the client end to simulate disconnect
            client.close()

            result = loop.run_until_complete(conn.send_event("hello"))
            assert result is False
        finally:
            loop.close()


class TestAsyncConnectionManager:
    def test_accept_and_dispatch(self):
        """Accept a connection then dispatch an event — data should arrive."""
        from plain.channels.handler import AsyncConnectionManager

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                # Accept
                await manager._accept_connection_async(fd, StubChannel(), ["test_chan"])
                assert len(manager._connections) == 1

                # Dispatch
                await manager.dispatch_event("test_chan", "payload123")

            loop.run_until_complete(run())

            # Read from client
            client.setblocking(True)
            client.settimeout(1.0)
            data = client.recv(8192)

            # Should contain headers + event
            assert b"HTTP/1.1 200 OK" in data
            assert b"data: payload123" in data
            assert b"event: test_chan" in data

            manager.close_all()
        finally:
            client.close()
            loop.close()

    def test_dispatch_to_wrong_channel_is_silent(self):
        """Dispatching to a channel no one subscribes to should be a no-op."""
        from plain.channels.handler import AsyncConnectionManager

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                await manager._accept_connection_async(fd, StubChannel(), ["test_chan"])
                await manager.dispatch_event("other_chan", "ignored")

            loop.run_until_complete(run())

            # Read — should only have headers, no event
            client.setblocking(True)
            client.settimeout(0.2)
            data = client.recv(8192)
            assert b"HTTP/1.1 200 OK" in data
            assert b"data:" not in data

            manager.close_all()
        finally:
            client.close()
            loop.close()

    def test_dead_connection_removed_on_dispatch(self):
        """If a client disconnects, dispatch should remove it."""
        from plain.channels.handler import AsyncConnectionManager

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                await manager._accept_connection_async(fd, StubChannel(), ["test_chan"])
                assert len(manager._connections) == 1

                # Close client to simulate disconnect
                client.close()

                # Dispatch — should detect dead connection
                await manager.dispatch_event("test_chan", "hello")

                assert len(manager._connections) == 0

            loop.run_until_complete(run())

            manager.close_all()
        finally:
            if not client._closed:
                client.close()
            loop.close()

    def test_close_all(self):
        """close_all() should close all connections."""
        from plain.channels.handler import AsyncConnectionManager

        loop = asyncio.new_event_loop()
        fd1, client1 = _make_socket_pair()
        fd2, client2 = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                await manager._accept_connection_async(fd1, StubChannel(), ["a"])
                await manager._accept_connection_async(fd2, StubChannel(), ["b"])
                assert len(manager._connections) == 2

            loop.run_until_complete(run())

            manager.close_all()
            assert len(manager._connections) == 0
        finally:
            client1.close()
            client2.close()
            loop.close()

    def test_transform_modifies_payload(self):
        """Channel.transform() should be applied before sending."""
        from plain.channels.handler import AsyncConnectionManager

        class TransformChannel(Channel):
            path = "/transform/"

            def transform(self, channel_name, payload):
                return {"wrapped": payload}

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                await manager._accept_connection_async(fd, TransformChannel(), ["x"])
                await manager.dispatch_event("x", "raw")

            loop.run_until_complete(run())

            client.setblocking(True)
            client.settimeout(1.0)
            data = client.recv(8192)
            assert b'{"wrapped": "raw"}' in data

            manager.close_all()
        finally:
            client.close()
            loop.close()

    def test_transform_returning_none_skips_event(self):
        """If transform() returns None, the event should not be sent."""
        from plain.channels.handler import AsyncConnectionManager

        class FilterChannel(Channel):
            path = "/filter/"

            def transform(self, channel_name, payload):
                return None  # Skip all events

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                await manager._accept_connection_async(fd, FilterChannel(), ["x"])
                await manager.dispatch_event("x", "should_be_filtered")

            loop.run_until_complete(run())

            client.setblocking(True)
            client.settimeout(0.2)
            data = client.recv(8192)
            # Should only have headers, no event data
            assert b"data:" not in data

            manager.close_all()
        finally:
            client.close()
            loop.close()


# ===================================================================
# Level 3: Postgres integration tests (need DATABASE_URL)
# ===================================================================


def _can_connect_psycopg() -> bool:
    """Check if we can actually connect to Postgres via psycopg (async)."""
    if "DATABASE_URL" not in os.environ:
        return False
    try:
        import psycopg

        conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
        conn.close()
        return True
    except Exception:
        return False


needs_postgres = pytest.mark.skipif(
    not _can_connect_psycopg(),
    reason="Cannot connect to Postgres via psycopg — skipping integration tests",
)


@needs_postgres
class TestPostgresListener:
    def test_listener_receives_notification(self):
        """PostgresListener should receive Postgres NOTIFY events."""
        import psycopg

        from plain.channels.handler import AsyncConnectionManager
        from plain.channels.listener import PostgresListener

        conninfo = os.environ["DATABASE_URL"]
        loop = asyncio.new_event_loop()
        try:
            manager = AsyncConnectionManager(loop)
            # Track dispatched events
            dispatched: list[tuple[str, str]] = []

            async def tracking_dispatch(channel_name, payload):
                dispatched.append((channel_name, payload))

            manager.dispatch_event = tracking_dispatch  # type: ignore[assignment]

            async def run():
                listener = PostgresListener(loop, manager, conninfo=conninfo)
                listener.poll_timeout = 0.5
                await listener.start()
                await listener.listen("test_notify_chan")

                # Give the listener time to set up
                await asyncio.sleep(0.3)

                # Send a notification from a separate connection
                notify_conn = await psycopg.AsyncConnection.connect(
                    conninfo, autocommit=True
                )
                await notify_conn.execute(
                    "SELECT pg_notify('test_notify_chan', 'test_payload')"
                )
                await notify_conn.close()

                # Wait for the notification to arrive
                await asyncio.sleep(0.5)

                await listener.stop()

            loop.run_until_complete(run())

            assert len(dispatched) == 1
            assert dispatched[0] == ("test_notify_chan", "test_payload")
        finally:
            loop.close()

    def test_listener_ignores_unsubscribed_channels(self):
        """Notifications on unsubscribed channels should not be dispatched."""
        import psycopg

        from plain.channels.handler import AsyncConnectionManager
        from plain.channels.listener import PostgresListener

        conninfo = os.environ["DATABASE_URL"]
        loop = asyncio.new_event_loop()
        try:
            manager = AsyncConnectionManager(loop)
            dispatched: list[tuple[str, str]] = []

            async def tracking_dispatch(channel_name, payload):
                dispatched.append((channel_name, payload))

            manager.dispatch_event = tracking_dispatch  # type: ignore[assignment]

            async def run():
                listener = PostgresListener(loop, manager, conninfo=conninfo)
                listener.poll_timeout = 0.5
                await listener.start()
                await listener.listen("subscribed_chan")

                await asyncio.sleep(0.3)

                # Send to a channel we're NOT listening on
                notify_conn = await psycopg.AsyncConnection.connect(
                    conninfo, autocommit=True
                )
                await notify_conn.execute(
                    "SELECT pg_notify('other_chan', 'should_not_arrive')"
                )
                await notify_conn.close()

                await asyncio.sleep(0.5)
                await listener.stop()

            loop.run_until_complete(run())

            assert len(dispatched) == 0
        finally:
            loop.close()

    def test_unlisten_stops_notifications(self):
        """After UNLISTEN, notifications should no longer arrive."""
        import psycopg

        from plain.channels.handler import AsyncConnectionManager
        from plain.channels.listener import PostgresListener

        conninfo = os.environ["DATABASE_URL"]
        loop = asyncio.new_event_loop()
        try:
            manager = AsyncConnectionManager(loop)
            dispatched: list[tuple[str, str]] = []

            async def tracking_dispatch(channel_name, payload):
                dispatched.append((channel_name, payload))

            manager.dispatch_event = tracking_dispatch  # type: ignore[assignment]

            async def run():
                listener = PostgresListener(loop, manager, conninfo=conninfo)
                listener.poll_timeout = 0.5
                await listener.start()
                await listener.listen("temp_chan")
                await asyncio.sleep(0.3)

                # Send first notification — should arrive
                notify_conn = await psycopg.AsyncConnection.connect(
                    conninfo, autocommit=True
                )
                await notify_conn.execute("SELECT pg_notify('temp_chan', 'first')")
                await asyncio.sleep(0.5)
                assert len(dispatched) == 1

                # Unlisten
                await listener.unlisten("temp_chan")
                await asyncio.sleep(0.1)

                # Send second notification — should NOT arrive
                await notify_conn.execute("SELECT pg_notify('temp_chan', 'second')")
                await asyncio.sleep(0.5)
                await notify_conn.close()

                assert len(dispatched) == 1  # Still just the first one

                await listener.stop()

            loop.run_until_complete(run())
        finally:
            loop.close()


@needs_postgres
class TestFullPipeline:
    def test_notify_to_sse_client(self):
        """Full pipeline: pg_notify → PostgresListener → AsyncConnectionManager → SSE socket."""
        import psycopg

        from plain.channels.handler import AsyncConnectionManager
        from plain.channels.listener import PostgresListener

        conninfo = os.environ["DATABASE_URL"]
        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:

            async def run():
                manager = AsyncConnectionManager(loop)

                # Wire up the listener directly (bypassing start() which auto-creates one)
                listener = PostgresListener(loop, manager, conninfo=conninfo)
                listener.poll_timeout = 0.5
                manager._listener = listener
                await listener.start()

                # Accept an SSE connection
                await manager._accept_connection_async(fd, StubChannel(), ["test_chan"])

                # Subscribe the channel in the listener
                await listener.listen("test_chan")
                await asyncio.sleep(0.3)

                # Send a notification from a separate Postgres connection
                notify_conn = await psycopg.AsyncConnection.connect(
                    conninfo, autocommit=True
                )
                await notify_conn.execute("SELECT pg_notify('test_chan', 'real_event')")
                await notify_conn.close()

                # Wait for it to propagate
                await asyncio.sleep(0.5)

                await listener.stop()
                manager.close_all()

            loop.run_until_complete(run())

            # Read everything the SSE client received
            client.setblocking(True)
            client.settimeout(1.0)
            data = client.recv(8192)

            # Should have HTTP headers
            assert b"HTTP/1.1 200 OK" in data
            assert b"text/event-stream" in data

            # Should have the event
            assert b"event: test_chan" in data
            assert b"data: real_event" in data

        finally:
            client.close()
            loop.close()
