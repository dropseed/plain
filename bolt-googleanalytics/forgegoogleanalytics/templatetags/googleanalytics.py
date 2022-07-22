from django import template
from django.conf import settings as django_settings

from .. import settings
from ..utils import user_id_from_request

register = template.Library()


@register.inclusion_tag("googleanalytics/js.html", takes_context=True)
def googleanalytics_js(context):
    if django_settings.DEBUG:
        return {}

    ctx = {
        "googleanalytics_measurement_id": settings.GOOGLEANALYTICS_MEASUREMENT_ID(),
    }

    if "request" in context:
        ctx["googleanalytics_user_id"] = user_id_from_request(context["request"])

    return ctx
