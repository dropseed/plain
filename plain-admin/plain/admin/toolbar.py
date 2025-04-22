import sys
import traceback

from plain.runtime import settings
from plain.templates import Template
from plain.urls.exceptions import Resolver404
from plain.utils.safestring import mark_safe


class Toolbar:
    def __init__(self, request):
        self.request = request
        self.version = settings.ADMIN_TOOLBAR_VERSION

    def should_render(self):
        if settings.DEBUG:
            return True

        if hasattr(self.request, "impersonator"):
            return self.request.impersonator.is_admin

        if self.request.user:
            return self.request.user.is_admin

        return False

    def request_exception(self):
        # We can capture the exception currently being handled here, if any.
        exception = sys.exception()

        if exception and not isinstance(exception, Resolver404):
            exception._traceback_string = "".join(
                traceback.format_tb(exception.__traceback__)
            )
            return exception

    def get_panels(self):
        panels = [panel(self.request) for panel in _toolbar_panel_registry.get_panels()]

        if self.request_exception():
            exception = self.request_exception()
            panels = [
                _ExceptionToolbarPanel(self.request, exception),
            ] + panels

        return panels


class ToolbarPanel:
    name: str
    template_name: str

    def __init__(self, request):
        self.request = request

    def get_template_context(self):
        return {
            "request": self.request,
        }

    def render(self):
        template = Template(self.template_name)
        context = self.get_template_context()
        return mark_safe(template.render(context))


class _ToolbarPanelRegistry:
    def __init__(self):
        self._panels = {}

    def register_panel(self, panel_class):
        self._panels[panel_class.name] = panel_class

    def get_panels(self):
        return self._panels.values()


_toolbar_panel_registry = _ToolbarPanelRegistry()


def register_toolbar_panel(panel_class):
    _toolbar_panel_registry.register_panel(panel_class)
    return panel_class


class _ExceptionToolbarPanel(ToolbarPanel):
    name = "Exception"
    template_name = "toolbar/exception.html"

    def __init__(self, request, exception):
        super().__init__(request)
        self.exception = exception

    def get_template_context(self):
        context = super().get_template_context()
        context["exception"] = self.exception
        return context


@register_toolbar_panel
class _RequestToolbarPanel(ToolbarPanel):
    name = "Request"
    template_name = "toolbar/request.html"


@register_toolbar_panel
class _QuerystatsToolbarPanel(ToolbarPanel):
    name = "Querystats"
    template_name = "toolbar/querystats.html"
