from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from jinja2.runtime import Context

from plain.templates import register_template_extension
from plain.templates.jinja.extensions import InclusionTagExtension

from .toolbar import Toolbar


@register_template_extension
class ToolbarExtension(InclusionTagExtension):
    tags = {"toolbar"}
    template_name = "toolbar/toolbar.html"

    def get_context(self, context: Context, *args: Any, **kwargs: Any) -> Context:
        # Jinja's Context behaves like a Mapping at runtime but doesn't
        # declare so in its type stubs — cast to satisfy Toolbar's signature.
        context.vars["toolbar"] = Toolbar(context=cast(Mapping[str, Any], context))
        return context
