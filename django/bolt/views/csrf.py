from django.utils.decorators import method_decorator
from functools import wraps

def csrf_exempt(view_func):
    """Mark a view function as being exempt from the CSRF view protection."""

    # view_func.csrf_exempt = True would also work, but decorators are nicer
    # if they don't have side effects, so return a new function.
    @wraps(view_func)
    def wrapper_view(*args, **kwargs):
        return view_func(*args, **kwargs)

    wrapper_view.csrf_exempt = True
    return wrapper_view


@method_decorator(csrf_exempt, name="get_response")
class CsrfExemptViewMixin:
    def get_response(self):
        return super().get_response()
