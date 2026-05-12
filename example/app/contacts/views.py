from __future__ import annotations

from typing import Any

from plain.http import Response
from plain.urls import reverse_lazy
from plain.views import FormView, TemplateView

from .forms import ArchiveFilterForm, ArchiveSearchForm, ContactForm
from .models import ContactSubmission


class ContactView(FormView):
    template_name = "contacts/form.plain.html"
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
    template_name = "contacts/success.plain.html"


class ContactArchiveView(TemplateView):
    """Two forms (search + filter) on the same page, distinguished by prefix."""

    template_name = "contacts/archive.plain.html"

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
