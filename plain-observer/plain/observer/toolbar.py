from functools import cached_property

from plain.toolbar import ToolbarPanel, register_toolbar_panel

from .core import Observer


@register_toolbar_panel
class ObserverToolbarPanel(ToolbarPanel):
    name = "Observer"
    template_name = "toolbar/observer.html"
    button_template_name = "toolbar/observer_button.html"

    @cached_property
    def observer(self):
        """Get the Observer instance for this request."""
        return Observer(self.request)

    def get_template_context(self):
        context = super().get_template_context()
        context["observer"] = self.observer
        return context
