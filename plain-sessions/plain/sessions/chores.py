from plain.chores import register_chore
from plain.utils import timezone

from .models import Session


@register_chore("sessions")
def clear_expired():
    """
    Delete sessions that have expired.
    """
    result = Session.objects.filter(expires_at__lt=timezone.now()).delete()
    return f"{result[0]} expired sessions deleted"
