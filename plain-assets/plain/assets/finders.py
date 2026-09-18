from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from plain.packages import packages_registry
from plain.runtime import APP_PATH

_APP_ASSETS_DIR = APP_PATH / "assets"

_SKIP_ASSETS = (".DS_Store", ".gitignore")

# A top-level `src/` in any asset dir holds build inputs — a build tool's entry
# points and the modules they import. They are consumed by the build, never served.
_BUILD_INPUT_DIR = "src"

# A top-level `dist/` holds build output that is already content-hashed by the
# build tool. Plain serves it immutable without re-fingerprinting (skips its md5).
_BUILD_OUTPUT_DIR = "dist"


def is_build_output(url_path: str) -> bool:
    """Whether a url_path lives under the top-level `dist/` build-output dir."""
    return url_path.startswith(_BUILD_OUTPUT_DIR + os.sep)


class Asset:
    def __init__(self, *, url_path: str, absolute_path: str):
        self.url_path = url_path
        self.absolute_path = absolute_path

    def __str__(self) -> str:
        return self.url_path


def _iter_assets() -> Iterator[Asset]:
    """
    Iterate all valid asset files found in the installed
    packages and the app itself.
    """

    def __iter_assets_dir(path: str | Path) -> Iterator[tuple[str, str]]:
        at_root = True
        for root, dirs, files in os.walk(path):
            if at_root:
                # Prune the top-level `src/` build-input dir — only here at the
                # root (os.walk yields it first), never a nested `foo/src/`.
                dirs[:] = [d for d in dirs if d != _BUILD_INPUT_DIR]
                at_root = False
            for f in files:
                if f in _SKIP_ASSETS:
                    continue
                abs_path = os.path.join(root, f)
                url_path = os.path.relpath(abs_path, path)
                yield url_path, abs_path

    for asset_dir in _iter_asset_dirs():
        for url_path, abs_path in __iter_assets_dir(asset_dir):
            yield Asset(url_path=url_path, absolute_path=abs_path)


def _iter_asset_dirs() -> Iterator[str | Path]:
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
    if _APP_ASSETS_DIR.exists():
        yield _APP_ASSETS_DIR
