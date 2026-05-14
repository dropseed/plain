from .urls import get_asset_url


def asset(url_path: str) -> str:
    return get_asset_url(url_path)
