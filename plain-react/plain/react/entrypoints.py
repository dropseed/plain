from __future__ import annotations

from .vite import run_vite_build, run_vite_dev


def run_dev() -> None:
    """Entry point for plain.dev - starts Vite dev server alongside Plain."""
    run_vite_dev()


def run_build() -> None:
    """Entry point for plain.build - builds React assets for production."""
    run_vite_build()
