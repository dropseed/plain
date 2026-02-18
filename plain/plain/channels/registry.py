from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .channel import Channel


class ChannelRegistry:
    """Registry of Channel classes, keyed by their path."""

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def register(self, channel_class: type[Channel]) -> type[Channel]:
        """Register a Channel class. Can be used as a decorator."""
        instance = channel_class()
        if not instance.path:
            raise ValueError(f"{channel_class.__name__} must define a 'path' attribute")
        self._channels[instance.path] = instance
        return channel_class

    def match(self, path: str) -> Channel | None:
        """Find a registered channel matching the given path."""
        return self._channels.get(path)

    def get_all(self) -> dict[str, Channel]:
        """Return all registered channels."""
        return dict(self._channels)


channel_registry = ChannelRegistry()
