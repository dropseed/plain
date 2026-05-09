from __future__ import annotations

from typing import Any

from plain.http import Response
from plain.schema import BoundSchema
from plain.urls import reverse_lazy
from plain.views import SchemaView, TemplateView

from .models import ContactSubmission
from .schemas import (
    ArchiveFilterSchema,
    ArchiveSearchSchema,
    ContactSchema,
)


class ContactView(SchemaView[ContactSchema]):
    """Schema-based contact form. Replaces the previous ContactView/Form
    setup — same fields, same validation, same template."""

    schema_class = ContactSchema
    template_name = "contacts/form.html"
    success_url = reverse_lazy("contacts:success")

    def get_initial(self) -> dict[str, Any]:
        if name := self.request.query_params.get("name"):
            return {"name": name}
        return {}

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["ask_company"] = self.request.query_params.get("company") == "1"
        return context

    def schema_valid(self, result: ContactSchema) -> Response:
        submission = result.apply_to(ContactSubmission())
        # `company` is `str | None` on the schema; model wants `""` for null.
        submission.company = result.company or ""
        submission.save()
        return super().schema_valid(result)


class ContactSuccessView(TemplateView):
    template_name = "contacts/success.html"


class ContactArchiveView(TemplateView):
    """Two filter forms (search + filter) on the same page via prefix.

    Both are GET-style filters so they're rendered as unbound BoundSchemas
    against the existing template; the actual filtering reads raw
    query_params alongside.
    """

    template_name = "contacts/archive.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["search_form"] = BoundSchema(
            schema_class=ArchiveSearchSchema, prefix="q"
        )
        context["filter_form"] = BoundSchema(
            schema_class=ArchiveFilterSchema, prefix="f"
        )

        params = self.request.query_params
        query = ContactSubmission.query.all()
        if text := params.get("q-text"):
            query = query.filter(message__icontains=text)
        if subject := params.get("f-subject"):
            query = query.filter(subject=subject)
        if params.get("f-subscribed_only") == "on":
            query = query.filter(subscribe=True)

        context["submissions"] = list(query[:50])
        return context
