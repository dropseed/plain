from plain.chores import register_chore

from .models import CachedItem


@register_chore("cache")
def clear_expired() -> str:
    """
    Delete cache items that have expired.
    """
    result = CachedItem.query.expired().delete()  # type: ignore[attr-defined]
    return f"{result[0]} expired cache items deleted"
