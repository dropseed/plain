from . import preflight  # noqa
from .storage import assets_storage


def get_asset_url(path):
    return assets_storage.url(path)
