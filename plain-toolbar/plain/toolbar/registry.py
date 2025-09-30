class ToolbarItemRegistry:
    def __init__(self):
        self._items = {}

    def register_item(self, item_class):
        self._items[item_class.name] = item_class

    def get_items(self):
        return self._items.values()


# Global registry instance
registry = ToolbarItemRegistry()


def register_toolbar_item(item_class):
    """Decorator to register a toolbar item."""
    registry.register_item(item_class)
    return item_class
