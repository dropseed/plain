from django import template

from ..core import StaffToolbar

register = template.Library()


@register.inclusion_tag("stafftoolbar/stafftoolbar.html", takes_context=True)
def stafftoolbar(context, outer_class="", inner_class=""):
    context["stafftoolbar"] = StaffToolbar(request=context.get("request"))
    context["stafftoolbar_outer_class"] = outer_class
    context["stafftoolbar_inner_class"] = inner_class
    return context
