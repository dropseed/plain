from plain.toolbar import ToolbarItem, register_toolbar_item


@register_toolbar_item
class AdminToolbarItem(ToolbarItem):
    name = "Admin"
    button_template_name = "admin/toolbar/button.html"
