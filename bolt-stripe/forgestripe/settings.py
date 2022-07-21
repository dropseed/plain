from os import environ

import stripe
from django.conf import settings

if "STRIPE_SECRET_KEY" in environ:
    STRIPE_SECRET_KEY = environ["STRIPE_SECRET_KEY"]
else:
    STRIPE_SECRET_KEY = getattr(settings, "STRIPE_SECRET_KEY", None)

if "STRIPE_WEBHOOK_SECRET" in environ:
    STRIPE_WEBHOOK_SECRET = environ["STRIPE_WEBHOOK_SECRET"]
else:
    STRIPE_WEBHOOK_SECRET = getattr(settings, "STRIPE_WEBHOOK_SECRET", None)

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
