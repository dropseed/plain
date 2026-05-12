from plain.templates import register_template_global

from .urls import get_asset_url


@register_template_global
def asset(url_path: str) -> str:
    return get_asset_url(url_path)
