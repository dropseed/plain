from plain.chores import Chore, register_chore
from plain.runtime import settings
from plain.utils import timezone

from .models import Pageview


@register_chore
class ClearOldPageviews(Chore):
    """Delete old anonymous and authenticated pageviews."""

    def run(self) -> str:
        cutoff = timezone.now() - settings.PAGEVIEWS_ANONYMOUS_RETENTION_TIMEDELTA
        result = Pageview.query.filter(timestamp__lt=cutoff, user_id="").delete()
        output = f"{result[0]} anonymous pageviews deleted"

        cutoff = timezone.now() - settings.PAGEVIEWS_AUTHENTICATED_RETENTION_TIMEDELTA
        result = (
            Pageview.query.filter(timestamp__lt=cutoff).exclude(user_id="").delete()
        )
        output += f", {result[0]} authenticated pageviews deleted"

        return output
