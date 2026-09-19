"""Public contract for `{% fragment %}` and the `fragment=` render option.

A fragment is a named region of a template that can be rendered on its
own. The rule is *render everything, return one region*: asking for a
fragment still executes the whole template — every loop iterates, every
branch decides, every component renders — and the named block's output
is what comes back. That is what makes a fragment inside a `{% for %}`
see exactly the scope it sees on a full render.

- A normal render emits the fragment inline, like any other content.
- `render(..., fragment="name")` returns only that block's output.
- Names are expressions, so a loop can compute one per iteration; the
  value is compared as `str(...)` because the name arrives over HTTP.
- Fragments nest: the outer capture contains the inner one's output.
- An unknown name raises `FragmentNotFound`, naming the template.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from plain.html import FragmentNotFound, Template, render, render_source

LOOP = (
    "{% for item in items %}"
    '<div>{% fragment "item-" + str(item["id"]) %}'
    "<b>{{ item['name'] }}</b>"
    "{% endfragment %}</div>"
    "{% endfor %}"
)
ITEMS = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}, {"id": 3, "name": "C"}]


def _app_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from plain.runtime import settings

    app_dir = tmp_path / "app"
    (app_dir / "templates").mkdir(parents=True)
    monkeypatch.setattr(settings, "path", app_dir / "settings.py")
    return app_dir


# --- inline rendering -------------------------------------------------------


def test_full_render_emits_the_fragment_inline() -> None:
    out = render_source(
        '<section>{% fragment "main" %}<p>Hello {{ name }}</p>{% endfragment %}</section>',
        {"name": "World"},
    )
    assert out == "<section><p>Hello World</p></section>"


def test_full_render_of_a_loop_emits_every_fragment() -> None:
    out = render_source(LOOP, {"items": ITEMS})
    assert out == "<div><b>A</b></div><div><b>B</b></div><div><b>C</b></div>"


# --- fragment rendering -----------------------------------------------------


def test_fragment_returns_only_that_region() -> None:
    out = render_source(
        '<section>{% fragment "main" %}<p>Hello</p>{% endfragment %}</section>',
        {},
        fragment="main",
    )
    assert out == "<p>Hello</p>"


def test_fragment_sees_the_render_context() -> None:
    out = render_source(
        '{% fragment "main" %}<p>Hello {{ name }}</p>{% endfragment %}',
        {"name": "World"},
        fragment="main",
    )
    assert out == "<p>Hello World</p>"


def test_fragment_picks_the_named_one_of_several() -> None:
    src = (
        '{% fragment "first" %}<p>AAA</p>{% endfragment %}'
        '{% fragment "second" %}<p>BBB</p>{% endfragment %}'
    )
    assert render_source(src, {}, fragment="second") == "<p>BBB</p>"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("item-1", "<b>A</b>"), ("item-2", "<b>B</b>"), ("item-3", "<b>C</b>")],
)
def test_fragment_in_a_loop_returns_that_iteration(name: str, expected: str) -> None:
    assert render_source(LOOP, {"items": ITEMS}, fragment=name) == expected


def test_fragment_name_is_compared_as_a_string() -> None:
    """Names arrive over HTTP, so a numeric expression still matches."""
    src = (
        "{% for i in ids %}{% fragment i %}<i>{{ i }}</i>{% endfragment %}{% endfor %}"
    )
    assert render_source(src, {"ids": [1, 2, 3]}, fragment="2") == "<i>2</i>"


def test_fragment_inside_a_conditional_branch() -> None:
    src = '{% if show %}{% fragment "a" %}<p>A</p>{% endfragment %}{% endif %}'
    assert render_source(src, {"show": True}, fragment="a") == "<p>A</p>"


def test_repeated_name_returns_the_first_occurrence() -> None:
    src = (
        "{% for n in names %}"
        '{% fragment "same" %}<p>{{ n }}</p>{% endfragment %}'
        "{% endfor %}"
    )
    out = render_source(src, {"names": ["one", "two"]}, fragment="same")
    assert out == "<p>one</p>"


# --- nesting ----------------------------------------------------------------


def test_inner_fragment_is_reachable_through_an_outer_one() -> None:
    src = (
        '{% fragment "outer" %}<p>BEFORE</p>'
        '{% fragment "inner" %}<b>INNER</b>{% endfragment %}'
        "<p>AFTER</p>{% endfragment %}"
    )
    assert render_source(src, {}, fragment="inner") == "<b>INNER</b>"


def test_outer_fragment_keeps_the_inner_one_inline() -> None:
    src = (
        '{% fragment "outer" %}<p>BEFORE</p>'
        '{% fragment "inner" %}<b>INNER</b>{% endfragment %}'
        "<p>AFTER</p>{% endfragment %}"
    )
    out = render_source(src, {}, fragment="outer")
    assert out == "<p>BEFORE</p><b>INNER</b><p>AFTER</p>"


# --- components -------------------------------------------------------------


def test_fragment_inside_a_component_is_reachable_from_the_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app_dir(tmp_path, monkeypatch)
    (app / "templates" / "Panel.html").write_text(
        "---\nattrs:\n  name: str\nslots:\n  default: required\n---\n"
        "<div>{% fragment name %}{{ children }}{% endfragment %}</div>"
    )
    (app / "templates" / "page.html").write_text(
        "---\ncomponents:\n  - Panel\n---\n"
        '<main><Panel name="body"><p>Hi</p></Panel></main>'
    )

    full = Template("page").render({})
    assert full == "<main><div><p>Hi</p></div></main>"
    assert Template("page").render({}, fragment="body") == "<p>Hi</p>"


def test_component_fragment_in_a_loop_gets_one_name_per_iteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app_dir(tmp_path, monkeypatch)
    (app / "templates" / "Panel.html").write_text(
        "---\nattrs:\n  name: str\nslots:\n  default: required\n---\n"
        "<div>{% fragment name %}{{ children }}{% endfragment %}</div>"
    )
    (app / "templates" / "list.html").write_text(
        "---\ncomponents:\n  - Panel\nattrs:\n  rows: list\n---\n"
        "<main>{% for row in rows %}"
        "<Panel name=\"{{ 'row-' + row }}\"><p>{{ row }}</p></Panel>"
        "{% endfor %}</main>"
    )

    assert Template("list").render({"rows": ["a", "b"]}, fragment="row-b") == "<p>b</p>"


# --- errors -----------------------------------------------------------------


def test_unknown_fragment_names_what_the_render_produced() -> None:
    src = '{% fragment "main" %}<p>Hello</p>{% endfragment %}'
    with pytest.raises(FragmentNotFound) as excinfo:
        render_source(src, {}, fragment="nope")
    message = str(excinfo.value)
    assert "'nope'" in message
    assert "'main'" in message


def test_unknown_fragment_says_when_a_declared_one_was_not_reached() -> None:
    src = '{% if show %}{% fragment "a" %}<p>A</p>{% endfragment %}{% endif %}'
    with pytest.raises(FragmentNotFound, match="none of them were reached"):
        render_source(src, {"show": False}, fragment="a")


def test_unknown_fragment_says_when_the_template_has_none() -> None:
    with pytest.raises(FragmentNotFound, match="declares no"):
        render_source("<p>nothing here</p>", {}, fragment="a")


def test_fragment_error_names_the_template_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app_dir(tmp_path, monkeypatch)
    path = app / "templates" / "page.html"
    path.write_text('{% fragment "main" %}<p>Hello</p>{% endfragment %}')

    with pytest.raises(FragmentNotFound, match="page.html"):
        render(path, {}, fragment="nope")


def test_rendering_a_fragment_does_not_mutate_the_context() -> None:
    context = {"name": "test"}
    render_source(
        '{% fragment "main" %}<p>{{ name }}</p>{% endfragment %}',
        context,
        fragment="main",
    )
    assert context == {"name": "test"}
