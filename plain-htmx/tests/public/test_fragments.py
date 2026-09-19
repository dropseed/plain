"""Public contract for HTMX fragment rendering.

`<HtmxFragment name="…">` wraps a region in a `[plain-hx-fragment]` div
whose contents are a `{% fragment %}` block. A normal request renders the
page with the wrapper and its contents. An HTMX request carrying
`Plain-HX-Fragment: <name>` gets just that block's output back, which is
what `hx-swap="innerHTML"` puts inside the wrapper.

These are the behaviors ported from the Jinja `{% htmxfragment %}` tag:
full render includes the wrapper, fragment render is contents-only,
context reaches the fragment, dynamic names work inside a loop, an outer
fragment keeps a nested one's wrapper, and an unknown name is an error.
"""

from __future__ import annotations

import pytest
from plain.html import FragmentNotFound
from plain.htmx.views import HTMXView
from plain.test import RequestFactory


def _request(*, fragment: str | None = None):
    headers = {"HX-Request": "true"}
    if fragment is not None:
        headers["Plain-HX-Fragment"] = fragment
    return RequestFactory().get("/", headers=headers)


class _View(HTMXView):
    template_name = "fragments.html"
    items = ({"id": 1, "name": "A"}, {"id": 2, "name": "B"})

    def get_template_context(self) -> dict:
        context = super().get_template_context()
        context["items"] = self.items
        context["name"] = "World"
        return context


def _render(*, fragment: str | None = None) -> str:
    return _View(request=_request(fragment=fragment)).render().content.decode()


# --- full render ------------------------------------------------------------


def test_full_render_includes_the_wrapper_and_contents() -> None:
    html = _render()
    assert 'plain-hx-fragment="main"' in html
    assert 'id="plain-hx-fragment-main"' in html
    assert 'hx-swap="innerHTML"' in html
    assert "Hello World" in html


def test_full_render_of_a_loop_emits_a_wrapper_per_item() -> None:
    html = _render()
    assert 'plain-hx-fragment="item-1"' in html
    assert 'plain-hx-fragment="item-2"' in html
    assert ">A<" in html
    assert ">B<" in html


# --- fragment render --------------------------------------------------------


def test_fragment_request_returns_contents_without_the_wrapper() -> None:
    html = _render(fragment="main")
    # The wrapper's contents, indented as authored — nothing else.
    assert html.strip() == "<p>Hello World</p>"
    assert "plain-hx-fragment" not in html


def test_fragment_request_sees_the_view_context() -> None:
    assert "World" in _render(fragment="main")


@pytest.mark.parametrize(("name", "expected"), [("item-1", "A"), ("item-2", "B")])
def test_fragment_in_a_loop_returns_that_iteration(name: str, expected: str) -> None:
    html = _render(fragment=name)
    # Only this iteration's content comes back — indented as authored.
    assert html.strip() == f"<span>{expected}</span>"


def test_targeting_an_outer_fragment_keeps_the_nested_wrapper() -> None:
    html = _render(fragment="outer")
    assert "BEFORE" in html
    assert "AFTER" in html
    assert 'plain-hx-fragment="inner"' in html
    assert "INNER" in html


def test_nested_fragment_is_reachable_on_its_own() -> None:
    html = _render(fragment="inner")
    assert html.strip() == "<b>INNER</b>"
    assert "BEFORE" not in html


def test_fragment_request_forwards_the_status_code() -> None:
    view = _View(request=_request(fragment="main"))
    assert view.render(status_code=422).status_code == 422


def test_unknown_fragment_name_raises() -> None:
    with pytest.raises(FragmentNotFound, match="nope"):
        _render(fragment="nope")


# --- header plumbing --------------------------------------------------------


def test_a_plain_htmx_request_without_a_fragment_renders_the_page() -> None:
    view = _View(request=_request())
    assert 'plain-hx-fragment="main"' in view.render().content.decode()


def test_the_fragment_header_is_in_vary() -> None:
    view = _View(request=_request(fragment="main"))
    response = view.after_response(view.render())
    assert "Plain-HX-Fragment" in response.headers["Vary"]
