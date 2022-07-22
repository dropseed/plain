from os import environ

from django.conf import settings


def STRIPE_SECRET_KEY():
    if "STRIPE_SECRET_KEY" in environ:
        return environ["STRIPE_SECRET_KEY"]
    else:
        return getattr(settings, "STRIPE_SECRET_KEY", None)


def STRIPE_WEBHOOK_SECRET():
    if "STRIPE_WEBHOOK_SECRET" in environ:
        return environ["STRIPE_WEBHOOK_SECRET"]
    else:
        return getattr(settings, "STRIPE_WEBHOOK_SECRET", None)
