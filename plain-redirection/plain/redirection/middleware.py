from plain.http import ResponseRedirect


class RedirectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if response.status_code == 404:
            from .models import NotFoundLog, Redirect, RedirectLog

            redirects = Redirect.objects.filter(enabled=True).only(
                "id", "from_pattern", "to_pattern", "http_status", "is_regex"
            )
            for redirect in redirects:
                if redirect.matches_request(request):
                    # Log it
                    redirect_log = RedirectLog.from_redirect(redirect, request)
                    # Then redirect
                    return ResponseRedirect(
                        redirect_log.to_url, status_code=redirect.http_status
                    )

            # Nothing matched, just log the 404
            NotFoundLog.from_request(request)

        return response
