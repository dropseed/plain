from bolt.jinja.extensions import InclusionTagExtension

from . import settings


class SentryScriptsExtension(InclusionTagExtension):
    tags = {"sentry_scripts"}
    template_name = "sentry/scripts.html"

    def get_context(self, context, *args, **kwargs):
        if not (settings.SENTRY_DSN() and settings.SENTRY_JS_ENABLED()):
            return {
                "sentry_js_enabled": False,
            }

        sentry_public_key = settings.SENTRY_DSN().split("//")[1].split("@")[0]

        sentry_context = {
            "sentry_js_enabled": True,
            "sentry_public_key": sentry_public_key,
            "sentry_dialog_event_id": context.get("sentry_dialog_event_id", None),
            "sentry_init": {
                "release": settings.SENTRY_RELEASE(),
                "environment": settings.SENTRY_ENVIRONMENT(),
                "sendDefaultPii": bool(settings.SENTRY_PII_ENABLED()),
            },
        }

        if "request" in context:
            # Use request.user by default (avoids accidental "user" variable confusion)
            user = getattr(context["request"], "user", None)
        else:
            # Get user directly if no request (like in server error context)
            user = context.get("user", None)

        if settings.SENTRY_PII_ENABLED() and user:
            sentry_context["sentry_init"]["initialScope"] = {
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.get_username(),
                }
            }

        return sentry_context


extensions = [
    SentryScriptsExtension,
]
