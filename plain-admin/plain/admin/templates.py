from typing import Any

from plain.packages import packages_registry
from plain.templates import register_template_filter, register_template_global

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
