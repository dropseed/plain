import stripe
from bolt.packages import PackageConfig

from . import settings


class BoltstripeConfig(PackageConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "bolt.stripe"

    def ready(self):
        if settings.STRIPE_SECRET_KEY():
            stripe.api_key = settings.STRIPE_SECRET_KEY()
