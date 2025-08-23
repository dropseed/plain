class ToolbarPanelRegistry:
    def __init__(self):
        self._panels = {}

    def register_panel(self, panel_class):
        self._panels[panel_class.name] = panel_class

    def get_panels(self):
        return self._panels.values()


# Global registry instance
registry = ToolbarPanelRegistry()


def register_toolbar_panel(panel_class):
    """Decorator to register a toolbar panel."""
    registry.register_panel(panel_class)
    return panel_class
