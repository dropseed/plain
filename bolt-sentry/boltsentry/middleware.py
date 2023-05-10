import sentry_sdk
from django.template import Context, Template


class SentryFeedbackMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if response.status_code == 500 and b"Sentry.onLoad" not in response.content:
            # Render the sentry_js tag manually, and insert it before the </head> tag
            # (this will work with any 500.html and uses minimal context)
            try:
                sentry_html = Template("{% load sentry %}{% sentry_js %}").render(
                    Context(
                        {
                            "sentry_dialog_event_id": sentry_sdk.last_event_id(),
                            "user": getattr(request, "user", None),
                        }
                    )
                )

                response.content = response.content.replace(
                    b"</head>",
                    sentry_html.encode("utf-8") + b"</head>",
                )
            except Exception:
                # Send the new error to sentry, but don't raise it again
                # (was our responsibility)
                sentry_sdk.capture_exception()

        return response
