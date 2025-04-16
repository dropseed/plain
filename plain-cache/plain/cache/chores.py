from plain.chores import register_chore

from .models import CachedItem


@register_chore("cache")
def clear_expired():
    """
    Delete cache items that have expired.
    """
    result = CachedItem.objects.expired().delete()
    return f"{result[0]} expired cache items deleted"
