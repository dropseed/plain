from plain.views import TemplateView


class CsrfFailureView(TemplateView):
    template_name = "403.html"

    def get_response(self):
        response = super().get_response()
        response.status_code = 403
        return response

    def post(self):
        return self.get()

    def put(self):
        return self.get()

    def patch(self):
        return self.get()

    def delete(self):
        return self.get()

    def head(self):
        return self.get()

    def options(self):
        return self.get()

    def trace(self):
        return self.get()
