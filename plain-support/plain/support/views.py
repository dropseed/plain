from plain.assets.urls import get_asset_url
from plain.http import ResponseRedirect
from plain.runtime import settings
from plain.utils.module_loading import import_string
from plain.views import FormView, View
from plain.views.csrf import CsrfExemptViewMixin


class SupportFormView(FormView):
    template_name = "support/page.html"

    def get_form(self):
        form_slug = self.url_kwargs["form_slug"]
        form_class = import_string(settings.SUPPORT_FORMS[form_slug])
        return form_class(**self.get_form_kwargs())

    def get_template_context(self):
        context = super().get_template_context()
        form_slug = self.url_kwargs["form_slug"]
        context["form_action"] = self.request.build_absolute_uri()
        context["form_template_name"] = f"support/forms/{form_slug}.html"
        context["success_template_name"] = f"support/success/{form_slug}.html"
        context["success"] = self.request.GET.get("success") == "true"
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        kwargs["form_slug"] = self.url_kwargs["form_slug"]
        return kwargs

    def form_valid(self, form):
        entry = form.save()
        form.notify(entry)
        return super().form_valid(form)

    def get_success_url(self, form):
        # Redirect to the same view and template so we
        # don't have to create two additional views for iframe and non-iframe.
        return "?success=true"


class SupportIFrameView(CsrfExemptViewMixin, SupportFormView):
    template_name = "support/iframe.html"

    def get_response(self):
        response = super().get_response()

        # X-Frame-Options are typically in DEFAULT_RESPONSE_HEADERS,
        # which will know to drop the header completely if an empty string.
        # We can't del/pop it because DEFAULT_RESPONSE_HEADERS may add it back.
        response.headers["X-Frame-Options"] = ""

        return response


class SupportFormJSView(View):
    def get(self):
        return ResponseRedirect(get_asset_url("support/embed.js"))
