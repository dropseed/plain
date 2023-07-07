from django.conf import settings


def FLAGS_MODULE():
    return getattr(settings, "FLAGS_MODULE", "flags")
