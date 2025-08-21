import tomllib
from pathlib import Path


def get_app_name_from_pyproject():
    """Get the project name from the nearest pyproject.toml file."""
    current_path = Path.cwd()

    # Walk up the directory tree looking for pyproject.toml
    for path in [current_path] + list(current_path.parents):
        pyproject_path = path / "pyproject.toml"
        if pyproject_path.exists():
            try:
                with pyproject_path.open("rb") as f:
                    pyproject = tomllib.load(f)
                    return pyproject.get("project", {}).get("name", "App")
            except (tomllib.TOMLDecodeError, OSError):
                continue

    return "App"
