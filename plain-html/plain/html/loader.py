"""Template file resolution.

Walks plain.html's own `get_html_dirs()` to map a template name like
`layouts/base` to a `.html` file on disk inside an `html/` directory.
Relative paths (`./x`, `../x`) resolve against the calling template's
directory.
"""

from __future__ import annotations

import functools
from pathlib import Path

from plain.packages import packages_registry
from plain.runtime import settings


class TemplateNotFound(FileNotFoundError):
    pass


def get_html_dirs() -> tuple[Path, ...]:
    """Return the ordered list of directories to search for plain.html templates.

    First the app's own `html/` directory, then each installed package's
    `html/` directory.
    """
    app_html = settings.path.parent / "html"
    return (app_html,) + _get_package_html_dirs()


@functools.lru_cache
def _get_package_html_dirs() -> tuple[Path, ...]:
    return tuple(
        Path(package_config.path) / "html"
        for package_config in packages_registry.get_package_configs()
        if package_config.path and (Path(package_config.path) / "html").is_dir()
    )


def find_template(name: str, *, current_template: Path | None = None) -> Path:
    """Resolve a template name to a `.html` file path under an `html/` dir.

    Absolute names (no leading `./` or `../`) walk `get_html_dirs()` in
    order; first match wins. Relative names resolve against `current_template`.
    """
    base_name = name.removesuffix(".html") if name.endswith(".html") else name
    filename = f"{base_name}.html"

    if name.startswith("./") or name.startswith("../"):
        if current_template is None:
            raise TemplateNotFound(
                f"Relative template path {name!r} requires a calling template"
            )
        candidate = (current_template.parent / filename).resolve()
        if candidate.exists():
            return candidate
        raise TemplateNotFound(name)

    for directory in get_html_dirs():
        candidate = Path(directory) / filename
        if candidate.exists():
            return candidate

    raise TemplateNotFound(name)
