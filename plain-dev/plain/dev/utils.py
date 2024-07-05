import importlib
from pathlib import Path


def plainpackage_installed(name: str) -> bool:
    try:
        importlib.import_module(f"plain.{name}")
        return True
    except ImportError:
        return False


def has_pyproject_toml(target_path):
    return (Path(target_path) / "pyproject.toml").exists()
