from __future__ import annotations

import jinja2
import pytest

from plain.htmx.templates import HTMXFragmentExtension, render_template_fragment


def make_env():
    return jinja2.Environment(extensions=[HTMXFragmentExtension])


def test_fragment_full_page_render():
    """Normal (non-fragment) render includes the wrapper div."""
    env = make_env()
    template = env.from_string('{% htmxfragment "main" %}Hello{% endhtmxfragment %}')
    html = template.render()
    assert 'plain-hx-fragment="main"' in html
    assert "Hello" in html


def test_render_template_fragment_static_name():
    """render_template_fragment returns only the inner content."""
    env = make_env()
    template = env.from_string(
        '<html>{% htmxfragment "main" %}Hello{% endhtmxfragment %}</html>'
    )
    result = render_template_fragment(
        template=template, fragment_name="main", context={}
    )
    assert result == "Hello"


def test_render_template_fragment_with_context():
    """Fragment rendering has access to view context variables."""
    env = make_env()
    template = env.from_string(
        '{% htmxfragment "main" %}Hello {{ name }}{% endhtmxfragment %}'
    )
    result = render_template_fragment(
        template=template, fragment_name="main", context={"name": "World"}
    )
    assert result == "Hello World"


def test_render_template_fragment_in_loop():
    """Fragment with a dynamic name works inside a for loop."""
    env = make_env()
    template = env.from_string(
        "{% for item in items %}"
        '{% htmxfragment "item-" ~ item.id %}'
        "{{ item.name }}"
        "{% endhtmxfragment %}"
        "{% endfor %}"
    )
    items = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}, {"id": 3, "name": "C"}]
    result = render_template_fragment(
        template=template, fragment_name="item-2", context={"items": items}
    )
    assert result == "B"


def test_render_template_fragment_in_loop_first_item():
    env = make_env()
    template = env.from_string(
        "{% for item in items %}"
        '{% htmxfragment "item-" ~ item.id %}'
        "{{ item.name }}"
        "{% endhtmxfragment %}"
        "{% endfor %}"
    )
    items = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
    result = render_template_fragment(
        template=template, fragment_name="item-1", context={"items": items}
    )
    assert result == "A"


def test_render_template_fragment_in_loop_last_item():
    env = make_env()
    template = env.from_string(
        "{% for item in items %}"
        '{% htmxfragment "item-" ~ item.id %}'
        "{{ item.name }}"
        "{% endhtmxfragment %}"
        "{% endfor %}"
    )
    items = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
    result = render_template_fragment(
        template=template, fragment_name="item-2", context={"items": items}
    )
    assert result == "B"


def test_loop_fragment_full_page_render():
    """Full page render of loop fragments includes wrapper divs with dynamic names."""
    env = make_env()
    template = env.from_string(
        "{% for item in items %}"
        '{% htmxfragment "item-" ~ item.id %}'
        "{{ item.name }}"
        "{% endhtmxfragment %}"
        "{% endfor %}"
    )
    items = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
    html = template.render(items=items)
    assert 'plain-hx-fragment="item-1"' in html
    assert 'plain-hx-fragment="item-2"' in html
    assert "A" in html
    assert "B" in html


def test_fragment_not_found():
    env = make_env()
    template = env.from_string('{% htmxfragment "main" %}Hello{% endhtmxfragment %}')
    with pytest.raises(jinja2.TemplateNotFound, match="nonexistent"):
        render_template_fragment(
            template=template, fragment_name="nonexistent", context={}
        )


def test_multiple_fragments_targets_correct_one():
    env = make_env()
    template = env.from_string(
        '{% htmxfragment "first" %}AAA{% endhtmxfragment %}'
        '{% htmxfragment "second" %}BBB{% endhtmxfragment %}'
    )
    result = render_template_fragment(
        template=template, fragment_name="second", context={}
    )
    assert result == "BBB"


def test_nested_fragment_inside_non_target():
    """A target fragment nested inside a non-target fragment is still found."""
    env = make_env()
    template = env.from_string(
        '{% htmxfragment "outer" %}'
        'OUTER{% htmxfragment "inner" %}INNER{% endhtmxfragment %}'
        "{% endhtmxfragment %}"
    )
    result = render_template_fragment(
        template=template, fragment_name="inner", context={}
    )
    assert result == "INNER"


def test_nested_fragment_keeps_wrapper_when_targeting_parent():
    """When targeting outer, inner fragment should keep its wrapper div."""
    env = make_env()
    template = env.from_string(
        '{% htmxfragment "outer" %}'
        'BEFORE{% htmxfragment "inner" %}INNER{% endhtmxfragment %}AFTER'
        "{% endhtmxfragment %}"
    )
    result = render_template_fragment(
        template=template, fragment_name="outer", context={}
    )
    assert 'plain-hx-fragment="inner"' in result
    assert "INNER" in result
    assert "BEFORE" in result
    assert "AFTER" in result


def test_non_string_fragment_name():
    """Dynamic fragment names that evaluate to non-string types still match."""
    env = make_env()
    template = env.from_string(
        "{% for item in items %}"
        "{% htmxfragment item.id %}"
        "{{ item.name }}"
        "{% endhtmxfragment %}"
        "{% endfor %}"
    )
    items = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
    # Header value is always a string, but the Jinja expression produces an int
    result = render_template_fragment(
        template=template, fragment_name="2", context={"items": items}
    )
    assert result == "B"


def test_context_not_mutated():
    """render_template_fragment should not mutate the caller's context dict."""
    env = make_env()
    template = env.from_string('{% htmxfragment "main" %}Hello{% endhtmxfragment %}')
    context = {"name": "test"}
    render_template_fragment(template=template, fragment_name="main", context=context)
    assert "_htmx_target_fragment" not in context
