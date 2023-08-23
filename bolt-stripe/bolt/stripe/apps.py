import stripe
from bolt.apps import AppConfig

from . import settings


class BoltstripeConfig(AppConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "bolt.stripe"

    def ready(self):
        if settings.STRIPE_SECRET_KEY():
            stripe.api_key = settings.STRIPE_SECRET_KEY()
