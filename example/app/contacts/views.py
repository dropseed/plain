from __future__ import annotations

from typing import Any

from plain.http import RedirectResponse, Response
from plain.schema import BoundSchema, Invalid
from plain.urls import reverse_lazy
from plain.views import FormView, TemplateView, View

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

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["ask_company"] = self.request.query_params.get("company") == "1"
        return context

    def form_valid(self, form: ContactForm) -> Response:
        form.save()
        return super().form_valid(form)


class ContactSchemaView(View):
    """Parallel to ContactView using plain.schema.Schema + BoundSchema.

    Same fields, same validation, same template — but Schema replaces the
    Form class. The view does the GET/POST orchestration explicitly so
    the data flow is visible top-to-bottom.
    """

    def get(self) -> Response:
        initial: dict[str, Any] = {}
        if name := self.request.query_params.get("name"):
            initial["name"] = name
        bound = BoundSchema(schema_class=ContactSchema, initial=initial)
        return self.render_template_response(bound)

    def post(self) -> Response:
        result = ContactSchema.validate(self.request.form_data)
        if isinstance(result, Invalid):
            bound = BoundSchema.from_invalid(ContactSchema, result)
            return self.render_template_response(bound)

        # result IS the typed ContactSchema instance — attribute access
        # is statically typed without a `.data` indirection.
        ContactSubmission.query.create(
            name=result.name,
            email=result.email,
            subject=result.subject,
            message=result.message,
            company=result.company or "",
            subscribe=result.subscribe,
        )
        return RedirectResponse(reverse_lazy("contacts:success"))

    def render_template_response(self, form: BoundSchema) -> Response:
        from plain.templates import Template

        ask_company = self.request.query_params.get("company") == "1"
        return Response(
            Template("contacts/form.html").render(
                {
                    "form": form,
                    "ask_company": ask_company,
                    "request": self.request,
                }
            )
        )


class ContactSuccessView(TemplateView):
    template_name = "contacts/success.html"


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
