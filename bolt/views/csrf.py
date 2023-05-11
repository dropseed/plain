from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt


@method_decorator(csrf_exempt, name="get_response")
class CsrfExemptViewMixin:
    def get_response(self):
        return super().get_response()
