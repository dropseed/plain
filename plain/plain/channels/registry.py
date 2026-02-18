from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .channel import Channel


class ChannelRegistry:
    """Registry of Channel classes, keyed by their path."""

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}
        self._discovered = False

    def import_modules(self) -> None:
        """Import channel modules from installed packages and app to trigger registration."""
        if self._discovered:
            return
        from plain.packages import packages_registry

        packages_registry.autodiscover_modules("channels", include_app=True)
        self._discovered = True

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
