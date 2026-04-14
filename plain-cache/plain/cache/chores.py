from plain.chores import Chore, register_chore

from .models import CachedItem


@register_chore
class ClearExpired(Chore):
    """Delete cache items that have expired."""

    def run(self) -> str:
        count = CachedItem.query.expired().delete()
        return f"{count} expired cache items deleted"
