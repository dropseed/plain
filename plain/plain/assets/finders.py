import os

from plain.packages import packages_registry
from plain.runtime import APP_PATH

APP_ASSETS_DIR = APP_PATH / "assets"

SKIP_ASSETS = (".DS_Store", ".gitignore")


def iter_assets():
    """
    Iterate all valid asset files found in the installed
    packages and the app itself.
    """

    class Asset:
        def __init__(self, *, url_path, absolute_path):
            self.url_path = url_path
            self.absolute_path = absolute_path

        def __str__(self):
            return self.url_path

    def _iter_assets_dir(path):
        for root, _, files in os.walk(path):
            for f in files:
                if f in SKIP_ASSETS:
                    continue
                abs_path = os.path.join(root, f)
                url_path = os.path.relpath(abs_path, path)
                yield url_path, abs_path

    for asset_dir in iter_asset_dirs():
        for url_path, abs_path in _iter_assets_dir(asset_dir):
            yield Asset(url_path=url_path, absolute_path=abs_path)


def iter_asset_dirs():
    """
    Iterate all directories containing assets, from installed
    packages and from app/assets.
    """
    # Iterate the installed package assets, in order
    for pkg in packages_registry.get_package_configs():
        asset_dir = os.path.join(pkg.path, "assets")
        if os.path.exists(asset_dir):
            yield asset_dir

    # The app/assets take priority over everything
    yield APP_ASSETS_DIR
