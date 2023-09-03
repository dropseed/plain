import importlib
from pathlib import Path


def boltpackage_installed(name: str) -> bool:
    try:
        importlib.import_module(f"bolt.{name}")
        return True
    except ImportError:
        return False


def has_pyproject_toml(target_path):
    return (Path(target_path) / "pyproject.toml").exists()
