from plain.toolbar import ToolbarItem, register_toolbar_item


@register_toolbar_item
class SessionToolbarItem(ToolbarItem):
    name = "Session"
    panel_template_name = "toolbar/session.html"
