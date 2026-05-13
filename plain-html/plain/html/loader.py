"""Template file resolution.

Walks plain.html's own `get_html_dirs()` to map a template name like
`layouts/base` to a `.html` file on disk inside an `html/` directory.
Relative paths (`./x`, `../x`) resolve against the calling template's
directory.

Transitional fallback: while packages migrate, also probe
`<pkg>/templates/<name>.plain.html`. Drop the fallback once every
package has moved.
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


def _get_legacy_template_dirs() -> tuple[Path, ...]:
    """Transitional: the old `templates/` directories where `.plain.html`
    files still live for packages that haven't been migrated yet."""
    app_templates = settings.path.parent / "templates"
    pkg_templates = tuple(
        Path(package_config.path) / "templates"
        for package_config in packages_registry.get_package_configs()
        if package_config.path and (Path(package_config.path) / "templates").is_dir()
    )
    return (app_templates,) + pkg_templates


def find_template(name: str, *, current_template: Path | None = None) -> Path:
    """Resolve a template name to a `.html` file path under an `html/` dir.

    Absolute names (no leading `./` or `../`) walk `get_html_dirs()` in
    order; first match wins. Relative names resolve against `current_template`.

    Transitional: if no `<name>.html` is found under `html/`, fall back to
    `<name>.plain.html` under `templates/`. Remove this fallback once every
    package has migrated.
    """
    if name.endswith(".plain.html"):
        new_name = name.removesuffix(".plain.html")
    elif name.endswith(".html"):
        new_name = name.removesuffix(".html")
    else:
        new_name = name

    new_filename = f"{new_name}.html"
    legacy_filename = f"{new_name}.plain.html"

    if name.startswith("./") or name.startswith("../"):
        if current_template is None:
            raise TemplateNotFound(
                f"Relative template path {name!r} requires a calling template"
            )
        for filename in (new_filename, legacy_filename):
            candidate = (current_template.parent / filename).resolve()
            if candidate.exists():
                return candidate
        raise TemplateNotFound(name)

    for directory in get_html_dirs():
        candidate = Path(directory) / new_filename
        if candidate.exists():
            return candidate

    for directory in _get_legacy_template_dirs():
        candidate = Path(directory) / legacy_filename
        if candidate.exists():
            return candidate

    raise TemplateNotFound(name)
