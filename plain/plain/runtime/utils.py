import tomllib
from pathlib import Path


def get_app_info_from_pyproject() -> tuple[str, str]:
    """Get the project name and version from the nearest pyproject.toml file."""
    current_path = Path.cwd()

    # Walk up the directory tree looking for pyproject.toml
    for path in [current_path] + list(current_path.parents):
        pyproject_path = path / "pyproject.toml"
        if pyproject_path.exists():
            try:
                with pyproject_path.open("rb") as f:
                    pyproject = tomllib.load(f)
                    project = pyproject.get("project", {})
                    name = project.get("name", "App")
                    version = project.get("version", "dev")
                    return name, version
            except (tomllib.TOMLDecodeError, OSError):
                continue

    return "App", "dev"
