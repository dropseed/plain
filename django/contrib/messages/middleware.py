from django.conf import settings
from django.contrib.messages.storage import default_storage


class MessageMiddleware:
    """
    Middleware that handles temporary messages.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request._messages = default_storage(request)

        # A higher middleware layer may return a request which does not contain
        # messages storage, so make no assumption that it will be there.
        response = self.get_response(request)
        if hasattr(request, "_messages"):
            unstored_messages = request._messages.update(response)
            if unstored_messages and settings.DEBUG:
                raise ValueError("Not all temporary messages could be stored.")
        return response
