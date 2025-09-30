from functools import cached_property

from plain.toolbar import ToolbarItem, register_toolbar_item

from .core import Observer


@register_toolbar_item
class ObserverToolbarItem(ToolbarItem):
    name = "Observer"
    panel_template_name = "toolbar/observer.html"
    button_template_name = "toolbar/observer_button.html"

    @cached_property
    def observer(self):
        """Get the Observer instance for this request."""
        return Observer(self.request)

    def get_template_context(self):
        context = super().get_template_context()
        context["observer"] = self.observer
        return context
