import re

from django.template.context import make_context
from django.template.loader_tags import ExtendsNode
from django.template.response import TemplateResponse

from .templatetags.htmx import HTMXFragmentNode


class HTMXTemplateFragmentResponse(TemplateResponse):
    def __init__(self, htmx_fragment_name, *args, **kwargs):
        self.htmx_fragment_name = htmx_fragment_name
        super().__init__(*args, **kwargs)

    @property
    def rendered_content(self) -> str:
        template = self.resolve_template(self.template_name)
        context = self.resolve_context(self.context_data)

        # The base template obj is wrapped in DjangoTemplate, etc.
        template_base = template.template

        if len(template_base.nodelist) == 1 and isinstance(
            template_base.nodelist[0], ExtendsNode
        ):
            # If the template extends another,
            # the whole thing is wrapped in ExtendsNode
            nodelist = template_base.nodelist[0].nodelist
        else:
            nodelist = template_base.nodelist

        target_fragment_name = self.htmx_fragment_name

        for node in nodelist.get_nodes_by_type(HTMXFragmentNode):
            if node.fragment_name == target_fragment_name:
                # Render the node by itself, so we don't mess
                # with the template stored in memory
                context = make_context(context, self._request)
                with context.bind_template(template_base):
                    context.template_name = template_base.name
                    return node.render(
                        context,
                        allow_lazy=False,  # We're rendeirng a single fragment, so lazy is not allowed at this point
                    )

        raise ValueError(
            f"HTMX fragment {target_fragment_name} not found in template {template_base.name}"
        )


class HTMXViewMixin:
    htmx_template_name = ""
    htmx_fragment_response_class = HTMXTemplateFragmentResponse

    def render_to_response(self, context, **response_kwargs):
        if self.is_htmx_request and self.htmx_fragment_name:
            response_kwargs.setdefault("content_type", self.content_type)
            return self.htmx_fragment_response_class(
                htmx_fragment_name=self.htmx_fragment_name,
                # The regular kwargs
                request=self.request,
                template=self.get_template_names(),
                context=context,
                using=self.template_engine,
                **response_kwargs,
            )

        return super().render_to_response(context, **response_kwargs)

    def dispatch(self, *args, **kwargs):
        if self.is_htmx_request:
            # You can use an htmx_{method} method on views
            # (or htmx_{method}_{action} for specific actions)
            method = f"htmx_{self.request.method.lower()}"
            if self.htmx_action_name:
                method += f"_{self.htmx_action_name}"

            handler = getattr(self, method, None)
            if handler:
                return handler(self.request, *args, **kwargs)

        return super().dispatch(self.request, *args, **kwargs)

    def get_template_names(self):
        # TODO is this part necessary anymore?? can I replace those with fragments now?
        if self.is_htmx_request:
            if self.htmx_template_name:
                return [self.htmx_template_name]

            default_template_names = super().get_template_names()
            return [
                re.sub(r"\.html$", "_htmx.html", template_name)
                for template_name in default_template_names
            ] + default_template_names  # Fallback to the defaults so you don't need _htmx.html

        return super().get_template_names()

    @property
    def is_htmx_request(self):
        return self.request.headers.get("HX-Request") == "true"

    @property
    def htmx_fragment_name(self):
        # A custom header that we pass with the {% htmxfragment %} tag
        return self.request.headers.get("FHX-Fragment", "")

    @property
    def htmx_action_name(self):
        return self.request.headers.get("FHX-Action", "")
