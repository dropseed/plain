from os import environ

from django.conf import settings


def GOOGLEANALYTICS_MEASUREMENT_ID():
    if "GOOGLEANALYTICS_MEASUREMENT_ID" in environ:
        return environ["GOOGLEANALYTICS_MEASUREMENT_ID"]

    return getattr(settings, "GOOGLEANALYTICS_MEASUREMENT_ID", None)


def GOOGLEANALYTICS_API_SECRET():
    if "GOOGLEANALYTICS_API_SECRET" in environ:
        return environ["GOOGLEANALYTICS_API_SECRET"]

    return getattr(settings, "GOOGLEANALYTICS_API_SECRET", None)
