from plain.chores import register_chore
from plain.runtime import settings
from plain.utils import timezone

from .models import Pageview


@register_chore("pageviews")
def clear_old_pageviews():
    """
    Delete old anonymous and authenticated pageviews.
    """

    cutoff = timezone.now() - settings.PAGEVIEWS_ANONYMOUS_RETENTION_TIMEDELTA
    result = Pageview.objects.filter(timestamp__lt=cutoff, user_id="").delete()
    output = f"{result[0]} anonymous pageviews deleted"

    cutoff = timezone.now() - settings.PAGEVIEWS_AUTHENTICATED_RETENTION_TIMEDELTA
    result = Pageview.objects.filter(timestamp__lt=cutoff).exclude(user_id="").delete()
    output += f", {result[0]} authenticated pageviews deleted"

    return output
