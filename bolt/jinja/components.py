import os
import re
from typing import TYPE_CHECKING

from jinja2 import nodes
from jinja2.ext import Extension
from jinja2.loaders import FileSystemLoader

from bolt.utils.functional import cached_property

if TYPE_CHECKING:
    from jinja2 import Environment


class FileSystemTemplateComponentsLoader(FileSystemLoader):
    def get_source(self, environment: "Environment", template: str):
        contents, path, uptodate = super().get_source(environment, template)

        # Clear components cache if it looks like a component changed
        # if os.path.splitext(path)[1] == ".html" and "components" in path and "template_components" in self.__dict__:
        #     del self.__dict__["template_components"]

        # If it's html, replace component tags
        if os.path.splitext(path)[1] == ".html":
            self._template_components_environment = (
                environment  # Save this so we can use it in template_components
            )
            contents = self.replace_template_component_tags(contents)

        return contents, path, uptodate

    @cached_property
    def template_components(self):
        components = []

        for searchpath in self.searchpath:
            components_dir = os.path.join(searchpath, "components")
            if os.path.isdir(components_dir):
                for root, dirs, files in os.walk(components_dir):
                    for file in files:
                        relative_path = os.path.relpath(
                            os.path.join(root, file), components_dir
                        )
                        # Replace slashes with .
                        component_name = os.path.splitext(relative_path)[0].replace(
                            os.sep, "."
                        )
                        components.append(
                            {
                                "path": relative_path,
                                "html_name": component_name,  # Uses . syntax
                                "tag_name": component_name.replace(
                                    ".", "_"
                                ),  # Uses _ syntax
                            }
                        )

        for component in components:
            component_name = component["html_name"]
            jinja_tag_name = component["tag_name"]
            component_relative_path = component["path"]

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
                        ["name:end" + self.jinja_tag_name], drop_needle=True
                    )

                    call = self.call_method(
                        "_render", args=args, kwargs=kwargs, lineno=lineno
                    )
                    return nodes.CallBlock(call, [], [], body).set_lineno(lineno)

                def _render(self, context, **kwargs):
                    template = self.environment.get_template(self.template_name)
                    return template.render({**context, **kwargs})

            # Create a new class on the fly
            NamedComponentExtension = type(
                f"HTMLComponent.{component_name}",
                (ComponentExtension,),
                {
                    "tags": {jinja_tag_name, f"end{jinja_tag_name}"},
                    "template_name": f"components/{component_relative_path}",
                    "jinja_tag_name": jinja_tag_name,
                },
            )
            self._template_components_environment.add_extension(NamedComponentExtension)

        return components

    def replace_template_component_tags(self, contents: str):
        def replace_quoted_braces(s) -> str:
            """
            We're converting to tag syntax, but it's very natural to write
            <Label for="{{ thing }}"> vs <Label for=thing>
            so we just convert the first to the second automatically.
            """
            return re.sub(r"(?<=\"{{)(.+)(?=}}\")", r"\1", s)

        for component in self.template_components:
            component_name = component["html_name"]
            jinja_tag_name = component["tag_name"]

            closing_pattern = re.compile(
                r"<{}(\s+[\s\S]*?)?>([\s\S]*?)</{}>".format(
                    component_name, component_name
                )
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
