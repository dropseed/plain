from __future__ import annotations

from plain.internal import internalcode

from .cli import build


@internalcode
def run_dev_build() -> None:
    # This will run by itself as a command, so it can exit()
    build(["--watch"], standalone_mode=True)


@internalcode
def run_build() -> None:
    # Standalone mode prevents it from exit()ing
    build(["--minify"], standalone_mode=False)
