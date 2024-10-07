from pathlib import Path


def has_pyproject_toml(target_path):
    return (Path(target_path) / "pyproject.toml").exists()
