from __future__ import annotations

from typing import Any

from jinja2 import nodes
from jinja2.ext import Extension


class InclusionTagExtension(Extension):
    """Intended to be subclassed"""

    # tags = {'inclusion_tag'}
    tags: set[str]
    template_name: str

    def parse(self, parser: Any) -> nodes.Node:
        lineno = next(parser.stream).lineno
        args = [
            nodes.DerivedContextReference(),
        ]
        kwargs = []
        while parser.stream.current.type != "block_end":
            if parser.stream.current.type == "name":
                key = parser.stream.current.value
                parser.stream.skip()
                parser.stream.expect("assign")
                value = parser.parse_expression()
                kwargs.append(nodes.Keyword(key, value))
            else:
                args.append(parser.parse_expression())

        call = self.call_method("_render", args=args, kwargs=kwargs, lineno=lineno)
        return nodes.CallBlock(call, [], [], []).set_lineno(lineno)

    def _render(self, context: dict[str, Any], *args: Any, **kwargs: Any) -> str:
        context = self.get_context(context, *args, **kwargs)
        template = self.environment.get_template(self.template_name)
        return template.render(context)

    def get_context(
        self, context: dict[str, Any], *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "You need to implement the `get_context` method in your subclass."
        )
