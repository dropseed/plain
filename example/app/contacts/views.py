from __future__ import annotations

from typing import Any

from plain.http import RedirectResponse, Response
from plain.schema import SchemaForm
from plain.schema.views import SchemaFormView
from plain.templates.views import FormView, TemplateView
from plain.urls import reverse, reverse_lazy

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


class ContactSchemaView(SchemaFormView[ContactSchema]):
    """The plain.schema counterpart to ContactView — the same page, on the
    app's `SchemaFormView` base instead of `FormView` + a `Form`.

    `ContactSchema` is a plain `Schema` (not model-backed) — there's no
    `querysets=` to scope, just `initial=` from the query string.
    """

    template_name = "contacts/schema_form.html"
    schema_class = ContactSchema

    def get_schema_form(self) -> SchemaForm[ContactSchema]:
        initial = {}
        if name := self.request.query_params.get("name"):
            initial = {"name": name}
        return SchemaForm(ContactSchema, self.request, initial=initial)

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["ask_company"] = self.request.query_params.get("company") == "1"
        return context

    def on_valid(self, result: ContactSchema) -> Response:
        # Schemas are pure data — persisting is the view's job. apply_to()
        # copies the validated fields onto a fresh model; the view saves it.
        result.apply_to(ContactSubmission()).save()
        return RedirectResponse(reverse("contacts:schema_success"))


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
