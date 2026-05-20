from __future__ import annotations

from typing import Any

from plain.http import RedirectResponse, Response
from plain.templates.views import TemplateView
from plain.urls import reverse

from .forms import ContactForm, ContactFormWithCompany
from .models import SUBJECT_CHOICES, ContactSubmission


class ContactView(TemplateView):
    """Showcase of a plain `Form`: GET renders it, POST validates and — on
    success — copies the cleaned values onto a new `ContactSubmission`.
    """

    template_name = "contacts/form.html"

    def get_form_class(self) -> type[ContactForm]:
        if self.request.query_params.get("company") == "1":
            return ContactFormWithCompany
        return ContactForm

    def get(self) -> Response:
        values: dict[str, Any] = {}
        if name := self.request.query_params.get("name"):
            values["name"] = name
        return self.render_form(self.get_form_class(), values=values)

    def post(self) -> Response:
        form_class = self.get_form_class()
        result = self.validate_form(form_class)
        if isinstance(result, Response):
            return result
        # ContactForm is a plain Form, not a ModelForm — build the row
        # explicitly from the validated, typed values.
        submission = ContactSubmission(
            name=result.name,
            email=result.email,
            subject=result.subject,
            message=result.message,
            subscribe=result.subscribe,
        )
        if isinstance(result, ContactFormWithCompany):
            submission.company = result.company or ""
        submission.save()
        return RedirectResponse(reverse("contacts:success"))


class ContactSuccessView(TemplateView):
    template_name = "contacts/success.html"


class ContactArchiveView(TemplateView):
    """A list page with two GET filters. Read-only filtering needs no `Form` —
    the view reads `query_params` straight through.
    """

    template_name = "contacts/archive.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        params = self.request.query_params

        search = params.get("search", "")
        subject = params.get("subject", "")
        subscribed_only = params.get("subscribed_only") == "on"

        query = ContactSubmission.query.all()
        if search:
            query = query.filter(message__icontains=search)
        if subject:
            query = query.filter(subject=subject)
        if subscribed_only:
            query = query.filter(subscribe=True)

        context["search"] = search
        context["subject"] = subject
        context["subscribed_only"] = subscribed_only
        context["subject_choices"] = SUBJECT_CHOICES
        context["submissions"] = list(query[:50])
        return context
