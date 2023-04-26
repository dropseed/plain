from . import settings


def can_be_impersonator(user):
    return settings.IMPERSONATE_ALLOWED(user)


def can_impersonate_user(impersonator, target_user):
    if not can_be_impersonator(impersonator):
        return False

    if target_user.is_superuser:
        # Nobody can impersonate superusers
        return False

    if target_user.is_staff and not impersonator.is_superuser:
        # Only superusers can impersonate other staff
        return False

    return True
