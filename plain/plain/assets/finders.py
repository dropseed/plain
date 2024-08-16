import os

from plain.packages import packages
from plain.runtime import APP_PATH

APP_ASSETS_DIR = APP_PATH / "assets"

SKIP_ASSETS = (".DS_Store", ".gitignore")


def find_assets():
    assets_map = {}

    class Asset:
        def __init__(self, *, url_path, absolute_path):
            self.url_path = url_path
            self.absolute_path = absolute_path

        def __str__(self):
            return self.url_path

    def iter_directory(path):
        for root, _, files in os.walk(path):
            for f in files:
                if f in SKIP_ASSETS:
                    continue
                abs_path = os.path.join(root, f)
                url_path = os.path.relpath(abs_path, path)
                yield url_path, abs_path

    # Iterate the installed package assets, in order
    for pkg in packages.get_package_configs():
        pkg_assets_dir = os.path.join(pkg.path, "assets")
        for url_path, abs_path in iter_directory(pkg_assets_dir):
            assets_map[url_path] = Asset(url_path=url_path, absolute_path=abs_path)

    # The app/assets take priority over everything
    for url_path, abs_path in iter_directory(APP_ASSETS_DIR):
        assets_map[url_path] = Asset(url_path=url_path, absolute_path=abs_path)

    return assets_map
