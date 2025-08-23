from plain.toolbar import ToolbarPanel, register_toolbar_panel


@register_toolbar_panel
class SessionToolbarPanel(ToolbarPanel):
    name = "Session"
    template_name = "toolbar/session.html"
