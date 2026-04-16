from __future__ import annotations

import json
from typing import Any

from plain.forms import BaseForm
from plain.http import Response
from plain.views import CreateView, UpdateView

from .forms import (
    ChildCascadeForm,
    DBDefaultsExampleForm,
    FormsExampleForm,
    SecretStoreForm,
)
from .models.forms import FormsExample


class _NoTemplateFormView:
    """Bypass template requirements in test views.

    CreateView/UpdateView normally need a template for GET and for
    form-invalid responses. These tests only exercise POST behavior, so
    we return plain Responses instead of rendering templates.
    """

    def get(self) -> Response:
        return Response("ok")

    def form_invalid(self, form: BaseForm) -> Response:
        errors: dict[str, list[str]] = {
            name: [str(err) for err in errs] for name, errs in form.errors.items()
        }
        return Response(
            json.dumps(errors),
            status_code=400,
            content_type="application/json",
        )


class FormsExampleCreateView(_NoTemplateFormView, CreateView):
    form_class = FormsExampleForm
    success_url = "/ok/"


class FormsExampleUpdateView(_NoTemplateFormView, UpdateView):
    form_class = FormsExampleForm
    success_url = "/ok/"

    def get_object(self) -> Any:
        return FormsExample.query.filter(id=self.url_kwargs["pk"]).first()


class ChildCascadeCreateView(_NoTemplateFormView, CreateView):
    form_class = ChildCascadeForm
    success_url = "/ok/"


class DBDefaultsExampleCreateView(_NoTemplateFormView, CreateView):
    form_class = DBDefaultsExampleForm
    success_url = "/ok/"


class SecretStoreCreateView(_NoTemplateFormView, CreateView):
    form_class = SecretStoreForm
    success_url = "/ok/"
