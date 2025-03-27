from plain.http import ResponseBase
from plain.templates import TemplateFileMissing

from .templates import TemplateView


class ErrorView(TemplateView):
    status_code: int

    def __init__(self, *, status_code=None, exception=None) -> None:
        # Allow creating an ErrorView with a status code
        # e.g. ErrorView.as_view(status_code=404)
        self.status_code = status_code or self.status_code

        # Allow creating an ErrorView with an exception
        self.exception = exception

    def get_template_context(self):
        context = super().get_template_context()
        context["status_code"] = self.status_code
        context["exception"] = self.exception
        return context

    def get_template_names(self) -> list[str]:
        return [f"{self.status_code}.html", "error.html"]

    def get_request_handler(self):
        return self.get  # All methods (post, patch, etc.) will use the get()

    def get_response(self) -> ResponseBase:
        response = super().get_response()
        # Set the status code we want
        response.status_code = self.status_code
        return response

    def get(self):
        try:
            return super().get()
        except TemplateFileMissing:
            return self.status_code
