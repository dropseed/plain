from bolt.jinja.extensions import InclusionTagExtension
from .core import StaffToolbar

class StaffToolbarExtension(InclusionTagExtension):
    tags = {"stafftoolbar"}
    template_name = "stafftoolbar/stafftoolbar.html"

    def get_context(self, context, *args, outer_class="", inner_class="", **kwargs):
        context.vars["stafftoolbar"] = StaffToolbar(request=context.get("request"))
        context.vars["stafftoolbar_outer_class"] = outer_class
        context.vars["stafftoolbar_inner_class"] = inner_class
        return context


extensions = [
    StaffToolbarExtension,
]
