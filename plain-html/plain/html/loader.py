"""Template file resolution.

Walks `get_template_dirs()` to map a template name like `layouts/base` to
a `.html` file on disk inside a `templates/` directory. Relative paths
(`./x`, `../x`) resolve against the calling template's directory.
"""

from __future__ import annotations

import functools
from pathlib import Path

from plain.packages import packages_registry
from plain.runtime import settings


class TemplateFileMissing(FileNotFoundError):
    """Raised by `find_template` when a template name can't be resolved
    to a `.html` file. Exported from `plain.html` as the public-facing
    exception; views and callers catch this to fall back to a default
    or surface a 404.
    """

    def __str__(self) -> str:
        if self.args:
            return f"Template file {self.args[0]} not found"
        else:
            return "Template file not found"


def get_template_dirs() -> tuple[Path, ...]:
    """Return the ordered list of directories to search for plain.html templates.

    First the app's own `templates/` directory, then each installed
    package's `templates/` directory.
    """
    app_templates = settings.path.parent / "templates"
    return (app_templates,) + _get_package_template_dirs()


@functools.lru_cache
def _get_package_template_dirs() -> tuple[Path, ...]:
    return tuple(
        Path(package_config.path) / "templates"
        for package_config in packages_registry.get_package_configs()
        if package_config.path and (Path(package_config.path) / "templates").is_dir()
    )


def find_template(name: str, *, current_template: Path | None = None) -> Path:
    """Resolve a template name to a `.html` file path under a `templates/` dir.

    Absolute names (no leading `./` or `../`) walk `get_template_dirs()` in
    order; first match wins. Relative names resolve against `current_template`.
    """
    base_name = name.removesuffix(".html") if name.endswith(".html") else name
    filename = f"{base_name}.html"

    if name.startswith("./") or name.startswith("../"):
        if current_template is None:
            raise TemplateFileMissing(
                f"Relative template path {name!r} requires a calling template"
            )
        candidate = (current_template.parent / filename).resolve()
        if candidate.exists():
            return candidate
        raise TemplateFileMissing(name)

    for directory in get_template_dirs():
        candidate = Path(directory) / filename
        if candidate.exists():
            return candidate

    raise TemplateFileMissing(name)
