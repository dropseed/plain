from django import template

from ..core import StaffToolbar

register = template.Library()


@register.inclusion_tag("stafftoolbar/stafftoolbar.html", takes_context=True)
def stafftoolbar(context, container_class=""):
    context["stafftoolbar"] = StaffToolbar(request=context.get("request"))
    context["stafftoolbar_container_class"] = container_class
    return context
