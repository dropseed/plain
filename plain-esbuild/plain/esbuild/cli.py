import os

import click
from watchfiles import Change, DefaultFilter, watch

from plain.assets.finders import _iter_asset_dirs, _iter_assets
from plain.cli import register_cli

from .core import JS_EXTENSIONS, esbuild, get_esbuilt_path


@register_cli("esbuild")
@click.group("esbuild")
def cli() -> None:
    pass


def _is_entry(path: str) -> bool:
    return ".esbuild." in os.path.basename(path)


def _build_entries(*, minify: bool) -> dict[str, set[str] | None]:
    """Build every entry, returning each entry's bundled input paths (None if its build failed)."""
    entry_inputs = {}
    for asset in _iter_assets():
        if _is_entry(asset.absolute_path):
            entry = os.path.realpath(asset.absolute_path)
            entry_inputs[entry] = esbuild(
                entry,
                get_esbuilt_path(entry),
                minify=minify,
            )
            print()
    return entry_inputs


@cli.command()
@click.option("--minify", is_flag=True, default=True)
def build(minify: bool) -> None:
    if None in _build_entries(minify=minify).values():
        exit(1)


@cli.command()
def dev() -> None:
    # Do an initial build of the assets
    entry_inputs = _build_entries(minify=False)

    asset_dirs = list(_iter_asset_dirs())

    class EsbuildFilter(DefaultFilter):
        ignore_entity_patterns = (
            *DefaultFilter.ignore_entity_patterns,
            r"\.tmp\.",
            r"\.esbuilt\.",
        )

        def __call__(self, change: Change, path: str) -> bool:
            return super().__call__(change, path) and (
                _is_entry(path) or path.endswith(JS_EXTENSIONS)
            )

    print("Watching asset source files...")

    for changes in watch(*asset_dirs, watch_filter=EsbuildFilter()):
        changed_paths = set()

        for change, path in changes:
            path = os.path.realpath(path)

            if _is_entry(path):
                if change == Change.deleted:
                    entry_inputs.pop(path, None)
                    dist_path = get_esbuilt_path(path)
                    if os.path.exists(dist_path):
                        print(f"Deleting {os.path.relpath(dist_path)}")
                        os.remove(dist_path)
                    continue

                # A new entry starts with no known inputs, so it gets built below
                entry_inputs.setdefault(path, None)

            changed_paths.add(path)

        # Rebuild the entries that bundled a changed file
        # (or whose last build failed, since any change might fix it)
        for entry, inputs in list(entry_inputs.items()):
            if inputs is None or inputs & changed_paths:
                entry_inputs[entry] = esbuild(
                    entry, get_esbuilt_path(entry), minify=False
                )
                print()
