from __future__ import annotations

from app.users.models import User

from plain.email import TemplateEmail
from plain.runtime import settings

from .models import SupportFormEntry


def find_user(email: str) -> User | None:
    """Look up a user by email to associate a support entry with them.

    The submitter often isn't logged in (typical in an iframe), so a match
    here doesn't confirm identity — subsequent email correspondence does.
    """
    if not email:
        return None
    try:
        return User.query.get(email=email)
    except User.DoesNotExist:
        return None


def notify_support(entry: SupportFormEntry) -> None:
    """Email the support team about a new support form entry."""
    TemplateEmail(
        template="support_form_entry",
        subject=f"Support request from {entry.name}",
        to=[settings.SUPPORT_EMAIL],
        reply_to=[str(entry.email)],
        context={"support_form_entry": entry},
    ).send()
