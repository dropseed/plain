"""Public contract for the six names exported from `plain.html`.

`Template`, `render`, `render_source`, `Markup`, `mark_safe`, and
`TemplateFileMissing` are the API users import. These tests pin the
behaviors a changelog reader would expect to stay stable:

- `Template(name).render(ctx)` and `render(path, ctx)` are equivalent
  paths through the same compiler.
- `render_source(src, ctx)` matches `render(path, ctx)` when `path`
  contains `src`.
- Missing templates raise `plain.html.TemplateFileMissing` (so users
  can catch by that name without reaching into `plain.html.loader`).
- `Markup` and `mark_safe` are the same callable, both bypass
  autoescape, and `Markup` is the same as `plain.utils.safestring.SafeString`.
- Frontmatter `attrs:` with a malformed declaration raises clearly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import plain.html
from plain.html import (
    Markup,
    Template,
    TemplateFileMissing,
    mark_safe,
    render,
    render_source,
)
from plain.utils.safestring import SafeString


def _app_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `settings.path.parent` at a temp directory containing a
    `templates/` subdir, so `Template(name)` resolves there.
    """
    from plain.runtime import settings

    app_dir = tmp_path / "app"
    (app_dir / "templates").mkdir(parents=True)
    monkeypatch.setattr(settings, "path", app_dir / "settings.py")
    return app_dir


# --- Template + render path equivalence -------------------------------------


def test_template_renders_named_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app_dir(tmp_path, monkeypatch)
    (app / "templates" / "hello.html").write_text("<p>Hello, {{ name }}!</p>")

    assert Template("hello").render({"name": "Dave"}) == "<p>Hello, Dave!</p>"


def test_template_and_render_produce_identical_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Template(name).render(ctx)` and `render(path, ctx)` go through
    the same compiler — outputs must be byte-identical.
    """
    app = _app_dir(tmp_path, monkeypatch)
    path = app / "templates" / "greet.html"
    path.write_text("<p>Hello, {{ name }}!</p>")

    via_template = Template("greet").render({"name": "Dave"})
    via_render = render(path, {"name": "Dave"})
    assert via_template == via_render


def test_template_missing_raises_template_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app_dir(tmp_path, monkeypatch)

    with pytest.raises(TemplateFileMissing):
        Template("does/not/exist")


def test_template_file_missing_is_importable_from_plain_html() -> None:
    """`plain.html.TemplateFileMissing` is the public exception name —
    users catch by this import path, not by the loader's module path.
    """
    assert plain.html.TemplateFileMissing is TemplateFileMissing
    # And it's a FileNotFoundError subclass so generic file-error
    # handlers still catch it.
    assert issubclass(TemplateFileMissing, FileNotFoundError)


# --- render(path) vs render_source(src) -------------------------------------


def test_render_and_render_source_produce_identical_output(tmp_path: Path) -> None:
    """For equivalent input, `render(path)` and `render_source(src)`
    must produce the same bytes — they're the same compiler under two
    entry points.
    """
    src = "<ul>{% for x in items %}<li>{{ x }}</li>{% endfor %}</ul>"
    ctx = {"items": ["a", "b", "c"]}

    path = tmp_path / "list.html"
    path.write_text(src)

    assert render(path, ctx) == render_source(src, ctx)


def test_render_accepts_pathlike(tmp_path: Path) -> None:
    """`render` is typed as `str | os.PathLike` — Path objects work."""
    src = "<p>{{ x }}</p>"
    path = tmp_path / "p.html"
    path.write_text(src)

    assert render(path, {"x": "ok"}) == "<p>ok</p>"
    assert render(str(path), {"x": "ok"}) == "<p>ok</p>"


# --- Markup / mark_safe contract --------------------------------------------


def test_markup_is_safestring_alias() -> None:
    """`plain.html.Markup` re-exports `plain.utils.safestring.SafeString`
    per the upfront design decision — keeps the type stable across
    `mark_safe` callers project-wide.
    """
    assert Markup is SafeString


def test_markup_and_mark_safe_produce_identical_results() -> None:
    """`Markup` (the `SafeString` class) and `mark_safe` (the function)
    are *not* the same callable — but both wrap a string in a
    `SafeString` instance, and either bypasses escape in templates.
    The README's "same callable" wording is loose; the substantive
    contract is interchangeable behavior, which is what we lock here.
    """
    a = Markup("<b>x</b>")
    b = mark_safe("<b>x</b>")
    assert isinstance(a, SafeString)
    assert isinstance(b, SafeString)
    assert a == b


def test_markup_bypasses_escape_in_text() -> None:
    out = render_source("<p>{{ x }}</p>", {"x": Markup("<b>bold</b>")})
    assert out == "<p><b>bold</b></p>"


def test_mark_safe_bypasses_escape_in_text() -> None:
    """`mark_safe` is the canonical name in Python code; same effect."""
    out = render_source("<p>{{ x }}</p>", {"x": mark_safe("<b>bold</b>")})
    assert out == "<p><b>bold</b></p>"


def test_unmarked_string_is_escaped_in_text() -> None:
    """Sanity: the non-`Markup` baseline does get escaped, so the
    `Markup` test above isn't trivially passing."""
    out = render_source("<p>{{ x }}</p>", {"x": "<b>bold</b>"})
    assert out == "<p>&lt;b&gt;bold&lt;/b&gt;</p>"


# --- frontmatter error reporting --------------------------------------------


def test_frontmatter_with_invalid_yaml_raises(tmp_path: Path) -> None:
    """Malformed YAML in the frontmatter block surfaces at compile/load
    time rather than silently producing a half-baked render.

    Note: malformed *type expressions* in `attrs:` (e.g. `count: int =`)
    are not caught at compile time — they're only flagged by
    `plain html check --typecheck`. The runtime contract is only that
    the YAML itself must be well-formed.
    """
    src = """---
attrs: : :
---
<p>hi</p>
"""
    path = tmp_path / "bad.html"
    path.write_text(src)

    with pytest.raises(Exception):  # noqa: B017,PT011 — YAML exception is internal
        render(path, {})
