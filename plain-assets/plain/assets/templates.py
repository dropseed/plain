from plain.html import register_global

from .urls import get_asset_url


@register_global
def asset(url_path: str) -> str:
    return get_asset_url(url_path)
