from typing import Any

from plain.html import Template, TemplateFileMissing
from plain.packages import packages_registry
from plain.templates import register_template_filter, register_template_global
from plain.utils.safestring import SafeString, mark_safe

from .views.registry import registry


@register_template_filter
def get_admin_model_detail_url(obj: Any) -> str | None:
    return registry.get_model_detail_url(obj)


@register_template_global
def is_package_installed(package_name: str) -> bool:
    try:
        packages_registry.get_package_config(package_name)
        return True
    except LookupError:
        return False


@register_template_global
def render_value_template(candidates: list[str], context: dict[str, Any]) -> SafeString:
    """Render the first existing template from a list of candidates.

    Mirrors Jinja's `{% include [list_of_names] %}` semantics for the
    admin's per-field value-template resolution. Returns Markup so the
    caller can interpolate it without re-escape.
    """
    for name in candidates:
        try:
            return mark_safe(Template(name).render(context))
        except TemplateFileMissing:
            continue
    return mark_safe("")
