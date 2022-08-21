import sentry_sdk
from django.apps import AppConfig
from sentry_sdk.integrations.django import DjangoIntegration

from . import settings


class ForgesentryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "forgesentry"

    def ready(self):
        if settings.SENTRY_DSN():
            sentry_sdk.init(
                settings.SENTRY_DSN(),
                release=settings.SENTRY_RELEASE(),
                environment=settings.SENTRY_ENVIRONMENT(),
                send_default_pii=settings.SENTRY_PII_ENABLED(),
                traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE(),
                integrations=[DjangoIntegration()],
                **settings.SENTRY_INIT_KWARGS(),
            )
