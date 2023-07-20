import re
from django.utils.functional import cached_property
import os
from jinja2.loaders import FileSystemLoader
from typing import TYPE_CHECKING
from jinja2.ext import Extension
from jinja2 import nodes

if TYPE_CHECKING:
    from jinja2 import Environment


class FileSystemHTMLComponentsLoader(FileSystemLoader):
    def get_source(self, environment: "Environment", template: str):
        contents, path, uptodate = super().get_source(environment, template)

        # Clear components cache if it looks like a component changed
        # if os.path.splitext(path)[1] == ".html" and "components" in path and "html_components" in self.__dict__:
        #     del self.__dict__["html_components"]

        # If it's html, replace component tags
        if os.path.splitext(path)[1] == ".html":
            self._html_components_environment = (
                environment  # Save this so we can use it in html_components
            )
            contents = self.replace_component_tags(contents)

        return contents, path, uptodate

    @cached_property
    def html_components(self):
        components = []

        for searchpath in self.searchpath:
            components_dir = os.path.join(searchpath, "components")
            if os.path.isdir(components_dir):
                for component in os.listdir(components_dir):
                    component_name = os.path.splitext(component)[0]
                    # Nesting below components/{sub}/component.html is not supported...
                    component_path = os.path.join(components_dir, component)
                    if os.path.isfile(component_path):
                        components.append(component_name)

        for component_name in components:
            class ComponentExtension(Extension):
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
                        ["name:end" + self.component_name], drop_needle=True
                    )

                    call = self.call_method(
                        "_render", args=args, kwargs=kwargs, lineno=lineno
                    )
                    return nodes.CallBlock(call, [], [], body).set_lineno(lineno)

                def _render(self, context, **kwargs):
                    template = self.environment.get_template(self.template_name)
                    return template.render({**context, **kwargs})

            # Create a new class on the fly
            NamedComponentExtension = type(f"HTMLComponent.{component_name}", (ComponentExtension,), {
                "tags": {component_name, f"end{component_name}"},
                "template_name": f"components/{component_name}.html",
                "component_name": component_name,
            })
            self._html_components_environment.add_extension(NamedComponentExtension)

        return components

    def replace_component_tags(self, contents: str):
        def replace_quoted_braces(s) -> str:
            """
            We're converting to tag syntax, but it's very natural to write
            <Label for="{{ thing }}"> vs <Label for=thing>
            so we just convert the first to the second automatically.
            """
            return s.replace("\"{{", "").replace("}}\"", "")

        for component_name in self.html_components:
            closing_pattern = re.compile(
                r"<{}(\s+[\s\S]*?)?>([\s\S]*?)</{}>".format(component_name, component_name)
            )
            self_closing_pattern = re.compile(
                r"<{}(\s+[\s\S]*?)?/>".format(component_name)
            )

            def closing_cb(match: re.Match) -> str:
                if f"<{component_name}" in match.group(2):
                    raise ValueError(
                        f"Component {component_name} cannot be nested in itself"
                    )

                attrs_str = match.group(1) or ""
                inner = match.group(2)

                attrs_str = replace_quoted_braces(attrs_str)
                return f"{{% {component_name} {attrs_str} %}}{inner}{{% end{component_name} %}}"

            contents = closing_pattern.sub(closing_cb, contents)

            def self_closing_cb(match: re.Match) -> str:
                attrs_str = match.group(1) or ""

                attrs_str = replace_quoted_braces(attrs_str)
                return f"{{% {component_name} {attrs_str} %}}{{% end{component_name} %}}"

            contents = self_closing_pattern.sub(self_closing_cb, contents)

        if match := re.search(r"<[A-Z].*>", contents):
            raise ValueError(
                f"Found unmatched uppercase tag in template: {match.group(0)}"
            )

        return contents
