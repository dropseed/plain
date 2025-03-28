import jinja2
from jinja2 import meta, nodes
from jinja2.ext import Extension

from plain.runtime import settings
from plain.templates import register_template_extension
from plain.templates.jinja.extensions import InclusionTagExtension


@register_template_extension
class HTMXJSExtension(InclusionTagExtension):
    tags = {"htmx_js"}
    template_name = "htmx/js.html"

    def get_context(self, context, *args, **kwargs):
        return {
            "csrf_header": settings.CSRF_HEADER_NAME,
            "csrf_token": context["csrf_token"],
            "DEBUG": settings.DEBUG,
            "extensions": kwargs.get("extensions", []),
        }


@register_template_extension
class HTMXFragmentExtension(Extension):
    tags = {"htmxfragment"}

    def __init__(self, environment):
        super().__init__(environment)
        environment.extend(htmx_fragment_nodes={})

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
        def attrs_to_str(attrs):
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
            if k.startswith("hx_"):
                attrs[k.replace("_", "-")] = v
            else:
                attrs[k] = v

        if render_lazy:
            attrs.setdefault("hx-swap", "outerHTML")
            attrs.setdefault("hx-target", "this")
            attrs.setdefault("hx-indicator", "this")
            attrs_str = attrs_to_str(attrs)
            return f'<{as_element} plain-hx-fragment="{fragment_name}" hx-get hx-trigger="plainhtmx:load from:body" {attrs_str}></{as_element}>'
        else:
            # Swap innerHTML so we can re-run hx calls inside the fragment automatically
            # (render_template_fragment won't render this part of the node again, just the inner nodes)
            attrs.setdefault("hx-swap", "innerHTML")
            attrs.setdefault("hx-target", "this")
            attrs.setdefault("hx-indicator", "this")
            # Add an id that you can use to target the fragment from outside the fragment
            attrs.setdefault("id", f"plain-hx-fragment-{fragment_name}")
            attrs_str = attrs_to_str(attrs)
            return f'<{as_element} plain-hx-fragment="{fragment_name}" {attrs_str}>{caller()}</{as_element}>'


def render_template_fragment(*, template, fragment_name, context):
    template = find_template_fragment(template, fragment_name)
    return template.render(context)


def find_template_fragment(template: jinja2.Template, fragment_name: str):
    # Look in this template for the fragment
    callblock_node = template.environment.htmx_fragment_nodes.get(
        template.name, {}
    ).get(fragment_name)

    if not callblock_node:
        # Look in other templates for this fragment
        matching_callblock_nodes = []
        for fragments in template.environment.htmx_fragment_nodes.values():
            if fragment_name in fragments:
                matching_callblock_nodes.append(fragments[fragment_name])

        if len(matching_callblock_nodes) == 0:
            # If we still haven't found anything, it's possible that we're
            # in a different/new worker/process and haven't parsed the related templates yet
            ast = template.environment.parse(
                template.environment.loader.get_source(
                    template.environment, template.name
                )[0]
            )
            for ref in meta.find_referenced_templates(ast):
                if ref not in template.environment.htmx_fragment_nodes:
                    # Trigger them to parse
                    template.environment.get_template(ref)

            # Now look again
            for fragments in template.environment.htmx_fragment_nodes.values():
                if fragment_name in fragments:
                    matching_callblock_nodes.append(fragments[fragment_name])

        if len(matching_callblock_nodes) == 1:
            callblock_node = matching_callblock_nodes[0]
        elif len(matching_callblock_nodes) > 1:
            raise jinja2.TemplateNotFound(
                f"Fragment {fragment_name} found in multiple templates. Use a more specific name."
            )
        else:
            raise jinja2.TemplateNotFound(
                f"Fragment {fragment_name} not found in any templates"
            )

    if not callblock_node:
        raise jinja2.TemplateNotFound(
            f"Fragment {fragment_name} not found in template {template.name}"
        )

    # Create a new template from the node
    template_node = jinja2.nodes.Template(callblock_node.body)
    return template.environment.from_string(template_node)
