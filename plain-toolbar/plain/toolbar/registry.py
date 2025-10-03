from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .toolbar import ToolbarItem


T = TypeVar("T", bound=type["ToolbarItem"])


class ToolbarItemRegistry:
    def __init__(self) -> None:
        self._items: dict[str, type[ToolbarItem]] = {}

    def register_item(self, item_class: type[ToolbarItem]) -> None:
        self._items[item_class.name] = item_class

    def get_items(self) -> list[type[ToolbarItem]]:
        return list(self._items.values())


# Global registry instance
registry = ToolbarItemRegistry()


def register_toolbar_item(item_class: T) -> T:
    """Decorator to register a toolbar item."""
    registry.register_item(item_class)
    return item_class
