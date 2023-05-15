import jinja2
from jinja2.ext import Extension
from bolt.jinja.extensions import InclusionTagExtension


class HTMXScriptsExtension(InclusionTagExtension):
    tags = {"htmx_scripts"}
    template_name = "htmx/scripts.html"

    def get_context(self, context, *args, **kwargs):
        return {
            "csrf_token": context["csrf_token"]
        }

class HTMXFragmentExtension(Extension):
    tags = {"htmxfragment"}

    def __init__(self, environment):
        super().__init__(environment)
        environment.htmx_fragment_nodes = {}

    def parse(self, parser):
        lineno = next(parser.stream).lineno

        fragment_name = parser.parse_expression()

        if parser.stream.current.type == "name" and parser.stream.current.value == "lazy":
            next(parser.stream)
            fragment_lazy = True
        else:
            fragment_lazy = False

        body = parser.parse_statements(["name:endhtmxfragment"], drop_needle=True)

        render_lazy = jinja2.nodes.Const(fragment_lazy)
        call = self.call_method('_render_htmx_fragment', args=[fragment_name, render_lazy, jinja2.nodes.ContextReference()])
        node = jinja2.nodes.CallBlock(call, [], [], body).set_lineno(lineno)

        # Store a reference to the node for later
        self.environment.htmx_fragment_nodes.setdefault(parser.name, {})[fragment_name.value] = node

        return node

    def _render_htmx_fragment(self, fragment_name, render_lazy, context, caller):
        if render_lazy:
            return f'<div hx-get hx-trigger="bhxLoad from:body" bhx-fragment="{fragment_name}" hx-swap="outerHTML" hx-target="this" hx-indicator="this"></div>'
        else:
            return f'<div bhx-fragment="{fragment_name}" hx-swap="outerHTML" hx-target="this" hx-indicator="this">{caller()}</div>'

    @staticmethod
    def find_template_fragment(template: jinja2.Template, fragment_name: str):
        callblock_node = template.environment.htmx_fragment_nodes.get(template.name, {}).get(fragment_name)
        if not callblock_node:
            raise jinja2.TemplateNotFound(f"Fragment {fragment_name} not found in template {template.name}")

        # Create a new template from the node
        template_node = jinja2.nodes.Template(callblock_node.body)
        return template.environment.from_string(template_node)


    @staticmethod
    def render_template_fragment(*, template, fragment_name, context):
        template = HTMXFragmentExtension.find_template_fragment(template, fragment_name)
        return template.render(context)


extensions = [
    HTMXScriptsExtension,
    HTMXFragmentExtension,
]
