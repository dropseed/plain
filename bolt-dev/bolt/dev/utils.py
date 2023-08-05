import importlib
import subprocess
from pathlib import Path

import click


def boltpackage_installed(name: str) -> bool:
    try:
        importlib.import_module(f"bolt.{name}")
        return True
    except ImportError:
        return False


def get_repo_root():
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                stderr=subprocess.DEVNULL,
            )
            .decode("utf-8")
            .strip()
        )
    except subprocess.CalledProcessError:
        click.secho(
            "All bolt projects are expected to be in a git repo and we couldn't find one.",
            fg="red",
        )
        exit(1)


def has_pyproject_toml(target_path):
    return (Path(target_path) / "pyproject.toml").exists()
