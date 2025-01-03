from plain.templates import register_template_extension
from plain.templates.jinja.extensions import InclusionTagExtension
from plain.urls import reverse


@register_template_extension
class PageviewsJSExtension(InclusionTagExtension):
    tags = {"pageviews_js"}
    template_name = "pageviews/js.html"

    def get_context(self, context, *args, **kwargs):
        return {
            "pageviews_track_url": reverse("pageviews:track"),
        }
