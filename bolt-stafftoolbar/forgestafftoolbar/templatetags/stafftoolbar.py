from django import template

from ..core import StaffToolbar

register = template.Library()


@register.inclusion_tag("stafftoolbar/stafftoolbar.html", takes_context=True)
def stafftoolbar(context):
    context["stafftoolbar"] = StaffToolbar(request=context.get("request"))
    return context
