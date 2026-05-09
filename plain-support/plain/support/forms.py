from __future__ import annotations

from typing import TYPE_CHECKING

from plain.email import TemplateEmail
from plain.runtime import settings
from plain.schema import Schema, types

from .models import SupportFormEntry

if TYPE_CHECKING:
    from app.users.models import User


class SupportSchema(Schema):
    """The default support schema. Customization point — subclass to
    change validation, override `save()`/`notify()` for custom behavior.
    """

    name: str = types.TextField(max_length=255)
    email: str = types.EmailField()
    message: str = types.TextField()

    def find_user(self) -> User | None:
        # If the request isn't authenticated (typical in an iframe), look
        # up the user by submitted email so the entry is associated.
        # Subsequent email exchange confirms ownership.
        from app.users.models import User

        try:
            return User.query.get(email=self.email)
        except User.DoesNotExist:
            return None

    def save(self, *, user: User | None, form_slug: str) -> SupportFormEntry:
        return SupportFormEntry.query.create(
            name=self.name,
            email=self.email,
            message=self.message,
            user=user or self.find_user(),
            form_slug=form_slug,
        )

    def notify(self, entry: SupportFormEntry, *, user: User | None) -> None:
        """Notify the support team of a new entry. Sends an email by default."""
        email = TemplateEmail(
            template="support_form_entry",
            subject=f"Support request from {entry.name}",
            to=[settings.SUPPORT_EMAIL],
            reply_to=[str(entry.email)],
            context={"support_form_entry": entry},
        )
        email.send()
