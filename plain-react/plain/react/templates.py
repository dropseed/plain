from __future__ import annotations

import json
from typing import Any

from jinja2 import nodes
from jinja2.ext import Extension
from jinja2.runtime import Context

from plain.json import PlainJSONEncoder
from plain.templates import register_template_extension


@register_template_extension
class ReactComponentExtension(Extension):
    """
    Jinja2 template tag for embedding individual React components.

    Usage in templates:

        {% react "Chart" data=chart_data title="Revenue" %}

    Renders a mount point that the client-side `mountIslands()` picks up:

        <div data-react-component="Chart" data-react-props='{"data": [...], "title": "Revenue"}'></div>
    """

    tags = {"react"}

    def parse(self, parser: Any) -> nodes.Node:
        lineno = next(parser.stream).lineno

        # First argument: component name (string)
        args = [
            parser.parse_expression(),
            nodes.DerivedContextReference(),
        ]

        # Remaining keyword arguments become props
        kwargs = []
        while parser.stream.current.type != "block_end":
            if parser.stream.current.type == "name":
                key = parser.stream.current.value
                parser.stream.skip()
                parser.stream.expect("assign")
                value = parser.parse_expression()
                kwargs.append(nodes.Keyword(key, value))

        call = self.call_method("_render", args=args, kwargs=kwargs, lineno=lineno)
        return nodes.CallBlock(call, [], [], []).set_lineno(lineno)

    def _render(
        self, component_name: str, context: Context, *args: Any, **kwargs: Any
    ) -> str:
        props_json = json.dumps(kwargs, cls=PlainJSONEncoder) if kwargs else ""

        # Escape for safe embedding in an HTML attribute
        escaped_json = (
            props_json.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

        props_attr = f' data-react-props="{escaped_json}"' if props_json else ""

        return f'<div data-react-component="{component_name}"{props_attr}></div>'
