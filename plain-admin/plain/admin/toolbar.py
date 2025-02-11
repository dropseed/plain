import sys
import traceback

from plain.runtime import settings
from plain.urls.exceptions import Resolver404


class Toolbar:
    def __init__(self, request):
        self.request = request
        self.version = settings.TOOLBAR_VERSION
        self.metadata = {
            "Request ID": request.unique_id,
        }

    def should_render(self):
        if settings.DEBUG:
            return True

        if hasattr(self.request, "impersonator"):
            return self.request.impersonator.is_admin

        if self.request.user:
            return self.request.user.is_admin

        return False

    def request_exception(self):
        # We can capture the exception currently being handled here, if any.
        exception = sys.exception()

        if exception and not isinstance(exception, Resolver404):
            exception._traceback_string = "".join(
                traceback.format_tb(exception.__traceback__)
            )
            return exception
