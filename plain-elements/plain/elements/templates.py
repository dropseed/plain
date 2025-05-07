import os
import re

from jinja2 import nodes, pass_context
from jinja2.ext import Extension

from plain.templates import register_template_extension
from plain.utils.safestring import mark_safe


@pass_context
def Element(ctx, name, **kwargs):
    element_path_name = name.replace(".", os.sep)
    template = ctx.environment.get_template(f"elements/{element_path_name}.html")

    if "caller" in kwargs and "children" not in kwargs:
        # If we have a caller, we need to pass it as the children
        kwargs["children"] = kwargs["caller"]()

    output = template.render(
        {
            # Note that this passes globals, but not things like loop variables
            # so for the most part you need to manually pass the kwargs you want
            **ctx.get_all(),
            **kwargs,
        }
    )
    return mark_safe(output)


@register_template_extension
class ElementsExtension(Extension):
    tags = {"use_elements"}

    def __init__(self, env):
        super().__init__(env)
        # Make the Element function available in connection with this extension
        env.globals["Element"] = Element

        self._CAP_TAG = r"(?:[a-z_]+\.)?[A-Z][A-Za-z0-9_]*"

        self._SELF = re.compile(
            rf"<(?P<name>{self._CAP_TAG})(?P<attrs>(?:\s+[^/>]*?)?)/>"
        )
        self._CLOSED = re.compile(
            rf"<(?P<name>{self._CAP_TAG})(?P<attrs>(?:\s+[^>]*?)?)>"
            rf"(?P<body>[\s\S]*?)"
            rf"</\1>"
        )

    def parse(self, parser):
        # Consume {% use_elements %} and output nothing
        parser.stream.skip()
        return nodes.Output([])

    def preprocess(self, source, name, filename=None):
        if "{% use_elements %}" in source:
            # If we have a use_elements tag, we need to replace the template element tags
            # with the Element() calls
            source = self.replace_template_element_tags(source)

        return source

    def replace_template_element_tags(self, contents: str):
        if not contents:
            return contents

        def repl_self(m: re.Match) -> str:
            return self.convert_element(m.group("name"), m.group("attrs") or "", "")

        def repl_closed(m: re.Match) -> str:
            body = m.group("body")
            if f"<{m.group('name')} " in body:
                raise ValueError(
                    f"Element {m.group('name')} cannot be nested in itself"
                )
            return self.convert_element(m.group("name"), m.group("attrs") or "", body)

        # keep stripping tags until we can’t find any more
        prev = None
        while prev != contents:
            prev = contents
            contents = self._SELF.sub(repl_self, contents)
            contents = self._CLOSED.sub(repl_closed, contents)

        if re.search(rf"<{self._CAP_TAG}", contents):
            raise ValueError("Found unmatched capitalized tag in template")

        return contents

    def convert_element(self, element_name, s: str, children: str):
        attrs: dict[str, str] = {}

        # Quoted attrs
        for k, v in re.findall(r'([a-zA-Z0-9_]+)="([^"]*)"', s):
            attrs[k] = f'"{v}"'
        for k, v in re.findall(r"([a-zA-Z0-9_]+)='([^']*)'", s):
            attrs[k] = f"'{v}'"

        # Bare attrs (assume they are strings)
        for k, v in re.findall(r"([a-zA-Z0-9_]+)=([a-zA-Z0-9_\.]+)", s):
            attrs[k] = f'"{v}"'

        # Braced Python variables (remove the braces)
        for k, raw in re.findall(r"([a-zA-Z0-9_]+)=({[^}]*})", s):
            expr = raw[1:-1]
            attrs[k] = expr

        attrs_str = ", ".join(f"{k}={v}" for k, v in attrs.items())
        if attrs_str:
            attrs_str = ", " + attrs_str

        call = f'{{% call Element("{element_name}"{attrs_str}) %}}{children}{{% endcall %}}'
        return call.strip()
