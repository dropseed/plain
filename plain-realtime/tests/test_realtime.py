"""Tests for plain.realtime SSEView."""

from plain.realtime.channel import SSEView


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
