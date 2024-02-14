import jinja2
from jinja2 import nodes
from jinja2.ext import Extension

from bolt.runtime import settings
from bolt.templates.jinja.extensions import InclusionTagExtension


class HTMXJSExtension(InclusionTagExtension):
    tags = {"htmx_js"}
    template_name = "htmx/js.html"

    def get_context(self, context, *args, **kwargs):
        return {
            "csrf_token": context["csrf_token"],
            "DEBUG": settings.DEBUG,
            "extensions": kwargs.get("extensions", []),
        }


class HTMXFragmentExtension(Extension):
    tags = {"htmxfragment"}

    def __init__(self, environment):
        super().__init__(environment)
        environment.htmx_fragment_nodes = {}

    def parse(self, parser):
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

        body = parser.parse_statements(["name:endhtmxfragment"], drop_needle=True)

        call = self.call_method(
            "_render_htmx_fragment",
            args=[fragment_name, jinja2.nodes.ContextReference()],
            kwargs=kwargs,
        )
        node = jinja2.nodes.CallBlock(call, [], [], body).set_lineno(lineno)

        # Store a reference to the node for later
        self.environment.htmx_fragment_nodes.setdefault(parser.name, {})[
            fragment_name.value
        ] = node

        return node

    def _render_htmx_fragment(self, fragment_name, context, caller, **kwargs):
        render_lazy = kwargs.get("lazy", False)
        hx_attributes = {
            k.replace("_", "-"): v for k, v in kwargs.items() if k.startswith("hx_")
        }

        def hx_attrs_to_str(attrs):
            parts = []
            for k, v in attrs.items():
                if v == "":
                    parts.append(k)
                else:
                    parts.append(f'{k}="{v}"')
            return " ".join(parts)

        if render_lazy:
            hx_attributes.setdefault("hx-swap", "outerHTML")
            hx_attributes.setdefault("hx-target", "this")
            hx_attributes.setdefault("hx-indicator", "this")
            hx_attrs = hx_attrs_to_str(hx_attributes)
            return f'<div bolt-hx-fragment="{fragment_name}" hx-get hx-trigger="bolthtmx:load from:body" {hx_attrs}></div>'
        else:
            # Swap innerHTML so we can re-run hx calls inside the fragment automatically
            # (render_template_fragment won't render this part of the node again, just the inner nodes)
            hx_attributes.setdefault("hx-swap", "innerHTML")
            hx_attributes.setdefault("hx-target", "this")
            hx_attributes.setdefault("hx-indicator", "this")
            hx_attrs = hx_attrs_to_str(hx_attributes)
            return (
                f'<div bolt-hx-fragment="{fragment_name}" {hx_attrs}>{caller()}</div>'
            )

    @staticmethod
    def find_template_fragment(template: jinja2.Template, fragment_name: str):
        callblock_node = template.environment.htmx_fragment_nodes.get(
            template.name, {}
        ).get(fragment_name)
        if not callblock_node:
            raise jinja2.TemplateNotFound(
                f"Fragment {fragment_name} not found in template {template.name}"
            )

        # Create a new template from the node
        template_node = jinja2.nodes.Template(callblock_node.body)
        return template.environment.from_string(template_node)

    @staticmethod
    def render_template_fragment(*, template, fragment_name, context):
        template = HTMXFragmentExtension.find_template_fragment(template, fragment_name)
        return template.render(context)


extensions = [
    HTMXJSExtension,
    HTMXFragmentExtension,
]
