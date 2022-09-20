import json

from django import template
from django.template.base import TextNode

register = template.Library()


@register.inclusion_tag("htmx/js.html", takes_context=True)
def htmx_js(context):
    if "request" not in context:
        # Should usually be available, but not always
        return {}

    return {
        "csrf_token": context["csrf_token"],
    }


class HTMXFragmentNode(template.Node):
    def __init__(self, fragment_name, nodelist, *args, **kwargs):
        self.fragment_name = fragment_name
        self.nodelist = template.NodeList(
            [
                TextNode(
                    f'<div fhx-fragment="{fragment_name}" hx-swap="outerHTML" hx-target="this" hx-indicator="this">'
                )
            ]
            + nodelist
            + [TextNode("</div>")]
        )
        super().__init__(*args, **kwargs)

    def render(self, context):
        return self.nodelist.render(context)


@register.tag
def htmxfragment(parser, token):
    tokens = token.split_contents()
    if len(tokens) != 2:
        raise template.TemplateSyntaxError(
            f"{tokens[0]} tag requires a single argument"
        )

    # This is a static string, not an expression
    fragment_name = tokens[1].strip("\"'")

    nodelist = parser.parse(("endhtmxfragment",))
    parser.delete_first_token()

    # TODO error if multiple fragments with the same name
    # TODO can we assign a reliable id to a node/fragment, so multiple of the same name can exist on a page? or in a loop?

    return HTMXFragmentNode(
        fragment_name=fragment_name,
        # fragment_id=fragment_id_expression,
        nodelist=nodelist,
    )
