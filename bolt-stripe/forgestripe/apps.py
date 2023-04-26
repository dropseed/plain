import stripe
from django.apps import AppConfig

from . import settings


class ForgestripeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "forgestripe"

    def ready(self):
        if settings.STRIPE_SECRET_KEY():
            stripe.api_key = settings.STRIPE_SECRET_KEY()
