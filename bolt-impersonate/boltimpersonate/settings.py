from django.conf import settings


def IMPERSONATE_ALLOWED(user):
    if hasattr(settings, "IMPERSONATE_ALLOWED"):
        return settings.IMPERSONATE_ALLOWED(user)

    return user.is_superuser or user.is_staff
