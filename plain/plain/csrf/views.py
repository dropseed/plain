from __future__ import annotations

from plain.http import Response
from plain.views import TemplateView


class CsrfFailureView(TemplateView):
    template_name = "403.html"

    def get_response(self) -> Response:
        response = super().get_response()
        response.status_code = 403
        return response

    def post(self) -> Response:
        return self.get()

    def put(self) -> Response:
        return self.get()

    def patch(self) -> Response:
        return self.get()

    def delete(self) -> Response:
        return self.get()

    def head(self) -> Response:
        return self.get()

    def options(self) -> Response:
        return self.get()

    def trace(self) -> Response:
        return self.get()
