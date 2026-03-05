"""Tests for plain.realtime SSEView and RealtimeWebSocketView."""

import asyncio

import pytest

from plain.realtime.channel import SSEView
from plain.realtime.websocket import RealtimeWebSocketView


class TestSSEViewBaseClass:
    def test_default_authorize(self):
        ch = SSEView()
        assert ch.authorize() is True

    def test_default_subscribe(self):
        ch = SSEView()
        assert ch.subscribe() == []

    def test_default_transform(self):
        ch = SSEView()
        assert ch.transform("chan", "payload") == "payload"


class TestRealtimeWebSocketViewSubscribe:
    def test_subscribe_allowed_during_connect_phase(self):
        """subscribe() works when _connect_phase is True (during connect)."""
        view = RealtimeWebSocketView()
        # _connect_phase is True by default (set in __init__)
        asyncio.run(view.subscribe("test_channel"))
        assert "test_channel" in view._subscriptions

    def test_subscribe_rejected_after_connect(self):
        """subscribe() raises RuntimeError after _after_connect() runs."""
        view = RealtimeWebSocketView()

        async def run():
            await view._after_connect()
            with pytest.raises(RuntimeError, match="must be called during connect"):
                await view.subscribe("late_channel")

        asyncio.run(run())
