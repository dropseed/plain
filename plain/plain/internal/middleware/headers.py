from plain.runtime import settings


class DefaultHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        for header, value in settings.DEFAULT_RESPONSE_HEADERS.items():
            response.headers.setdefault(header, value)

        # Add the Content-Length header to non-streaming responses if not
        # already set.
        if not response.streaming and not response.has_header("Content-Length"):
            response.headers["Content-Length"] = str(len(response.content))

        return response
