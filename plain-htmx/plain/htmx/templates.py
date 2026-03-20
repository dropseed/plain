from __future__ import annotations

from typing import Any

import jinja2
from jinja2 import nodes
from jinja2.ext import Extension
from jinja2.nodes import CallBlock, Node
from jinja2.parser import Parser
from jinja2.runtime import Context

from plain.runtime import settings
from plain.templates import register_template_extension
from plain.templates.jinja.extensions import InclusionTagExtension


@register_template_extension
class HTMXJSExtension(InclusionTagExtension):
    tags = {"htmx_js"}
    template_name = "htmx/js.html"

    def get_context(
        self, context: Context, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        request = context.get("request")
        return {
            "DEBUG": settings.DEBUG,
            "extensions": kwargs.get("extensions", []),
            "csp_nonce": request.csp_nonce if request else None,
        }


class _FragmentFound(Exception):
    """Raised to short-circuit template rendering once the target fragment is found."""

    def __init__(self, content: str) -> None:
        self.content = content


@register_template_extension
class HTMXFragmentExtension(Extension):
    tags = {"htmxfragment"}

    def parse(self, parser: Parser) -> Node:
        lineno = next(parser.stream).lineno

        fragment_name = parser.parse_expression()

        kwargs = []

        while parser.stream.current.type != "block_end":
            if parser.stream.current.type == "name":
                key = parser.stream.current.value
                parser.stream.skip()
                parser.stream.expect("assign")
                value = parser.parse_expression()
                kwargs.append(nodes.Keyword(key, value))

        body = parser.parse_statements(("name:endhtmxfragment",), drop_needle=True)

        call = self.call_method(
            "_render_htmx_fragment",
            args=[fragment_name, nodes.ContextReference()],
            kwargs=kwargs,
        )

        callblock = CallBlock(call, [], [], body)
        callblock.set_lineno(lineno)

        return callblock

    def _render_htmx_fragment(
        self, fragment_name: str, context: dict[str, Any], caller: Any, **kwargs: Any
    ) -> str:
        # Two-phase fragment targeting (see render_template_fragment):
        # Phase 1 skips non-target bodies, phase 2 renders them for nesting.
        # Once the target is found, "found" is set so child fragments render
        # normally with their wrapper divs.
        target_state = context.get("_htmx_target_fragment")
        if target_state is not None and not target_state["found"]:
            if str(fragment_name) == target_state["name"]:
                target_state["found"] = True
                content = caller()
                raise _FragmentFound(content)
            elif target_state["render_bodies"]:
                return caller()
            else:
                return ""

        def attrs_to_str(attrs: dict[str, Any]) -> str:
            parts = []
            for k, v in attrs.items():
                if v == "":
                    parts.append(k)
                else:
                    parts.append(f'{k}="{v}"')
            return " ".join(parts)

        render_lazy = kwargs.get("lazy", False)
        as_element = kwargs.get("as", "div")
        attrs = {}
        for k, v in kwargs.items():
            if k in ("lazy", "as"):
                continue
            if k.startswith("hx_"):
                attrs[k.replace("_", "-")] = v
            else:
                attrs[k] = v

        if render_lazy:
            attrs.setdefault("hx-trigger", "load from:body")
            attrs.setdefault("hx-swap", "outerHTML")
            attrs.setdefault("hx-target", "this")
            attrs.setdefault("hx-indicator", "this")
            attrs_str = attrs_to_str(attrs)
            return f'<{as_element} plain-hx-fragment="{fragment_name}" hx-get {attrs_str}></{as_element}>'
        else:
            # Swap innerHTML so we can re-run hx calls inside the fragment automatically
            attrs.setdefault("hx-swap", "innerHTML")
            attrs.setdefault("hx-target", "this")
            attrs.setdefault("hx-indicator", "this")
            # Add an id that you can use to target the fragment from outside the fragment
            attrs.setdefault("id", f"plain-hx-fragment-{fragment_name}")
            attrs_str = attrs_to_str(attrs)
            return f'<{as_element} plain-hx-fragment="{fragment_name}" {attrs_str}>{caller()}</{as_element}>'


def render_template_fragment(
    *, template: jinja2.Template, fragment_name: str, context: dict[str, Any]
) -> str:
    """Render only the named fragment from a template.

    Two-phase approach:
    1. Skip non-target fragment bodies (fast — handles top-level and loop fragments)
    2. If not found, render bodies too (handles fragments nested inside other fragments)

    Raises _FragmentFound to short-circuit as soon as the target is found.
    """
    for render_bodies in (False, True):
        target_state = {
            "name": fragment_name,
            "found": False,
            "render_bodies": render_bodies,
        }
        try:
            template.render({**context, "_htmx_target_fragment": target_state})
        except _FragmentFound as e:
            return e.content

    raise jinja2.TemplateNotFound(
        f"Fragment '{fragment_name}' not found in template {template.name}"
    )
