from __future__ import annotations

from typing import Any

from plain.http import Response
from plain.schema.views import SchemaView
from plain.templates.views import FormView, TemplateView
from plain.urls import reverse_lazy

from .forms import ArchiveFilterForm, ArchiveSearchForm, ContactForm
from .models import ContactSubmission
from .schemas import ContactSchema


class ContactView(FormView):
    template_name = "contacts/form.html"
    form_class = ContactForm
    success_url = reverse_lazy("contacts:success")

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["ask_company"] = self.request.query_params.get("company") == "1"
        if name := self.request.query_params.get("name"):
            kwargs["initial"] = {"name": name}
        return kwargs

    def form_valid(self, form: ContactForm) -> Response:
        form.save()
        return super().form_valid(form)


class ContactSuccessView(TemplateView):
    template_name = "contacts/success.html"


class ContactSchemaView(SchemaView[ContactSchema]):
    """The plain.schema counterpart to ContactView — same page, built on
    SchemaView + ContactSchema instead of FormView + ContactForm."""

    template_name = "contacts/schema_form.html"
    schema_class = ContactSchema
    success_url = reverse_lazy("contacts:schema_success")

    def get_initial(self) -> dict[str, Any]:
        if name := self.request.query_params.get("name"):
            return {"name": name}
        return {}

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["ask_company"] = self.request.query_params.get("company") == "1"
        return context

    def schema_valid(self, result: ContactSchema) -> Response:
        # Schemas are pure data — persisting is the view's job. apply_to()
        # copies the validated fields onto a fresh model; the view calls
        # save(). (ContactForm, by contrast, carries its own save() method.)
        result.apply_to(ContactSubmission()).save()
        return super().schema_valid(result)


class ContactSchemaSuccessView(TemplateView):
    template_name = "contacts/schema_success.html"


class ContactArchiveView(TemplateView):
    """Two forms (search + filter) on the same page, distinguished by prefix."""

    template_name = "contacts/archive.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        search = ArchiveSearchForm(request=self.request)
        filt = ArchiveFilterForm(request=self.request)

        # Both are unbound (GET-style) — read raw query_params for filtering.
        params = self.request.query_params
        query = ContactSubmission.query.all()
        if text := params.get("q-text"):
            query = query.filter(message__icontains=text)
        if subject := params.get("f-subject"):
            query = query.filter(subject=subject)
        if params.get("f-subscribed_only") == "on":
            query = query.filter(subscribe=True)

        context["search_form"] = search
        context["filter_form"] = filt
        context["submissions"] = list(query[:50])
        return context
