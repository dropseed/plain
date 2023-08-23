import sentry_sdk
from bolt.apps import AppConfig

from . import settings


class BoltsentryConfig(AppConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "bolt.sentry"

    def ready(self):
        if settings.SENTRY_DSN():
            sentry_sdk.init(
                settings.SENTRY_DSN(),
                release=settings.SENTRY_RELEASE(),
                environment=settings.SENTRY_ENVIRONMENT(),
                send_default_pii=settings.SENTRY_PII_ENABLED(),
                traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE(),
                auto_enabling_integrations=False,
                **settings.SENTRY_INIT_KWARGS(),
            )
