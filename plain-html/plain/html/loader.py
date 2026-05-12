"""Template file resolution.

Walks Plain's `get_template_dirs()` to map a template name like
`layouts/base` to a `.plain.html` file on disk. Relative paths (`./x`,
`../x`) resolve against the calling template's directory.
"""

from __future__ import annotations

from pathlib import Path

from plain.templates.jinja.environments import get_template_dirs


class TemplateNotFound(FileNotFoundError):
    pass


def find_template(name: str, *, current_template: Path | None = None) -> Path:
    """Resolve a template name to a `.plain.html` file path.

    Absolute names (no leading `./` or `../`) walk `get_template_dirs()` in
    order; first match wins. Relative names resolve against `current_template`.
    """
    name_with_ext = name if name.endswith(".plain.html") else f"{name}.plain.html"

    if name.startswith("./") or name.startswith("../"):
        if current_template is None:
            raise TemplateNotFound(
                f"Relative template path {name!r} requires a calling template"
            )
        candidate = (current_template.parent / name_with_ext).resolve()
        if candidate.exists():
            return candidate
        raise TemplateNotFound(name)

    for directory in get_template_dirs():
        candidate = Path(directory) / name_with_ext
        if candidate.exists():
            return candidate

    raise TemplateNotFound(name)
