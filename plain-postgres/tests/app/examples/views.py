"""Widget create/update/delete over HTTP.

The view-layer half of the ModelForm contract: `tests/public/test_modelform.py`
drives `validate()` / `create_from()` / `update_from()` directly, and
`tests/public/test_modelform_views.py` drives these views with a real client so
the whole round-trip — render, submit, re-render on failure, redirect, write —
is covered end to end.

Written the way an app writes them: explicit `get`/`post` on a `TemplateView`,
which is what the framework offers now that there is no generic `FormView`.
"""

from __future__ import annotations

from app.examples.models.relationships import Widget
from plain.html.views import DetailView, TemplateView
from plain.http import RedirectResponse, Response
from plain.postgres.forms import ModelForm, create_from, model_field, update_from


class WidgetForm(ModelForm):
    name = model_field(Widget.name)
    size = model_field(Widget.size)


class WidgetCreateView(TemplateView):
    template_name = "widgets/form.html"

    def get(self) -> Response:
        return self.render_form(WidgetForm)

    def post(self) -> Response:
        result = self.validate_form(WidgetForm)
        if isinstance(result, Response):
            return result
        widget = create_from(Widget, result)
        return RedirectResponse(f"/widgets/{widget.id}/edit", status_code=302)


class WidgetUpdateView(DetailView):
    template_name = "widgets/form.html"
    context_object_name = "widget"

    def get_object(self) -> Widget | None:
        return Widget.query.filter(id=self.url_kwargs["id"]).first()

    def get(self) -> Response:
        return self.render_form(WidgetForm, values=WidgetForm.initial_from(self.object))

    def post(self) -> Response:
        # `instance=` keeps this row out of its own uniqueness check.
        result = self.validate_form(WidgetForm, instance=self.object)
        if isinstance(result, Response):
            return result
        update_from(self.object, result)
        return RedirectResponse(f"/widgets/{self.object.id}/edit", status_code=302)


class WidgetDeleteView(DetailView):
    template_name = "widgets/confirm_delete.html"
    context_object_name = "widget"

    def get_object(self) -> Widget | None:
        return Widget.query.filter(id=self.url_kwargs["id"]).first()

    def post(self) -> Response:
        self.object.delete()
        return RedirectResponse("/widgets/new", status_code=302)
