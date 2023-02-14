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
    def __init__(self, fragment_name, nodelist, lazy, *args, **kwargs):
        self.fragment_name = fragment_name
        self.lazy = lazy
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

    def render(self, context, allow_lazy=True):
        if allow_lazy and self.lazy:
            return template.NodeList(
                [
                    TextNode(
                        f'<div hx-get hx-trigger="fhxLoad from:body" fhx-fragment="{self.fragment_name}" hx-swap="outerHTML" hx-target="this" hx-indicator="this"></div>'
                    ),
                ]
            ).render(context)

        return self.nodelist.render(context)


@register.tag
def htmxfragment(parser, token):
    tokens = token.split_contents()
    num_tokens = len(tokens)

    if num_tokens == 2:
        # This is a static string, not an expression
        fragment_name = tokens[1].strip("\"'")
        fragment_lazy = False
    elif num_tokens == 3:
        lazy_token = tokens[2]
        if lazy_token != "lazy":
            # Could support an expression later...
            raise template.TemplateSyntaxError(
                f"The second argument to {tokens[0]} tag must be 'lazy' or removed"
            )

        fragment_name = tokens[1].strip("\"'")
        fragment_lazy = True
    else:
        raise template.TemplateSyntaxError(
            f"{tokens[0]} tag requires a fragment name as single argument, or a fragment name and a lazy attribute"
        )

    nodelist = parser.parse(("endhtmxfragment",))
    parser.delete_first_token()

    # TODO error if multiple fragments with the same name
    # TODO can we assign a reliable id to a node/fragment, so multiple of the same name can exist on a page? or in a loop?

    return HTMXFragmentNode(
        fragment_name=fragment_name,
        # fragment_id=fragment_id_expression,
        nodelist=nodelist,
        lazy=fragment_lazy,
    )
