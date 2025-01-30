import os
import re

from jinja2 import nodes
from jinja2.ext import Extension

from plain.runtime import settings
from plain.templates import register_template_extension
from plain.utils.functional import cached_property


@register_template_extension
class ElementsExtension(Extension):
    def preprocess(self, source, name, filename=None):
        if not filename:
            # Assume we want to use it...
            return self.replace_template_element_tags(source)

        if os.path.splitext(filename)[1] in [".html", ".md"]:
            return self.replace_template_element_tags(source)

        return source

    @cached_property
    def template_elements(self):
        elements = []

        loader = self.environment.loader

        for searchpath in loader.searchpath:
            elements_dir = os.path.join(searchpath, "elements")
            if os.path.isdir(elements_dir):
                for root, dirs, files in os.walk(elements_dir):
                    for file in files:
                        relative_path = os.path.relpath(
                            os.path.join(root, file), elements_dir
                        )
                        # Replace slashes with .
                        element_name = os.path.splitext(relative_path)[0].replace(
                            os.sep, "."
                        )
                        elements.append(
                            {
                                "path": relative_path,
                                "html_name": element_name,  # Uses . syntax
                                "tag_name": element_name.replace(
                                    ".", "_"
                                ),  # Uses _ syntax
                            }
                        )

        for element in elements:
            element_name = element["html_name"]
            jinja_tag_name = element["tag_name"]
            element_relative_path = element["path"]

            class ElementExtension(Extension):
                def parse(self, parser):
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

                    body = parser.parse_statements(
                        ["name:end" + self.jinja_tag_name], drop_needle=True
                    )

                    call = self.call_method(
                        "_render", args=args, kwargs=kwargs, lineno=lineno
                    )

                    self.source_ref = f"{parser.name}:{lineno}"

                    return nodes.CallBlock(call, [], [], body).set_lineno(lineno)

                def _render(self, context, **kwargs):
                    template = self.environment.get_template(self.template_name)
                    rendered = template.render({**context, **kwargs})

                    if settings.DEBUG:
                        # Add an HTML comment in dev to help identify elements in output
                        return f"<!-- <{self.html_name}>\n{self.source_ref} -->\n{rendered}\n<!-- </{self.html_name}> -->"
                    else:
                        return rendered

            # Create a new class on the fly
            NamedElementExtension = type(
                f"PlainElement.{element_name}",
                (ElementExtension,),
                {
                    "tags": {jinja_tag_name, f"end{jinja_tag_name}"},
                    "template_name": f"elements/{element_relative_path}",
                    "jinja_tag_name": jinja_tag_name,
                    "html_name": element_name,
                },
            )
            self.environment.add_extension(NamedElementExtension)

        return elements

    def replace_template_element_tags(self, contents: str):
        def replace_quoted_braces(s) -> str:
            """
            We're converting to tag syntax, but it's very natural to write
            <Label for="{{ thing }}"> vs <Label for=thing>
            so we just convert the first to the second automatically.
            """
            return re.sub(r"(?<=\"{{)(.+)(?=}}\")", r"\1", s)

        for element in self.template_elements:
            element_name = element["html_name"]
            jinja_tag_name = element["tag_name"]

            closing_pattern = re.compile(
                rf"<{element_name}(\s+[\s\S]*?)?>([\s\S]*?)</{element_name}>"
            )
            self_closing_pattern = re.compile(rf"<{element_name}(\s+[\s\S]*?)?/>")

            def closing_cb(match: re.Match) -> str:
                if f"<{element_name}" in match.group(2):
                    raise ValueError(
                        f"Element {element_name} cannot be nested in itself"
                    )

                attrs_str = match.group(1) or ""
                inner = match.group(2)

                attrs_str = replace_quoted_braces(attrs_str)
                return f"{{% {jinja_tag_name} {attrs_str} %}}{inner}{{% end{jinja_tag_name} %}}"

            contents = closing_pattern.sub(closing_cb, contents)

            def self_closing_cb(match: re.Match) -> str:
                attrs_str = match.group(1) or ""

                attrs_str = replace_quoted_braces(attrs_str)
                return (
                    f"{{% {jinja_tag_name} {attrs_str} %}}{{% end{jinja_tag_name} %}}"
                )

            contents = self_closing_pattern.sub(self_closing_cb, contents)

        if match := re.search(r"<[A-Z].*>", contents):
            raise ValueError(
                f"Found unmatched uppercase tag in template: {match.group(0)}"
            )

        if match := re.search(r"<[a-z_]+\.[A-Z]+.*>", contents):
            raise ValueError(
                f"Found unmatched nested tag in template: {match.group(0)}"
            )

        return contents
