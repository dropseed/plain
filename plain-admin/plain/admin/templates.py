from plain.templates import register_template_filter

from .views.registry import registry


@register_template_filter
def get_admin_model_detail_url(obj):
    return registry.get_model_detail_url(obj)
