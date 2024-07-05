from plain.views import TemplateView


class CsrfFailureView(TemplateView):
    template_name = "403.html"

    def get(self):
        response = super().get()
        response.status_code = 403
        return response
