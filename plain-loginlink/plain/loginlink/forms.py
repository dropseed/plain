from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.email import TemplateEmail
from plain.schema import Schema, types

from app.users.models import User

from .links import generate_link_url

if TYPE_CHECKING:
    from plain.http import Request


class LoginLinkSchema(Schema):
    email: str = types.EmailField()
    next: str | None = types.TextField(required=False)

    def maybe_send_link(
        self, request: Request, expires_in: int = 60 * 60
    ) -> int | None:
        try:
            user = User.query.get(email__iexact=self.email)
        except User.DoesNotExist:
            user = None

        if user:
            url = generate_link_url(
                request=request, user=user, email=self.email, expires_in=expires_in
            )

            if self.next:
                url += f"?next={self.next}"

            email = self.get_template_email(
                email=self.email,
                context={"user": user, "url": url, "expires_in": expires_in},
            )
            return email.send()

        return None

    def get_template_email(
        self, *, email: str, context: dict[str, Any]
    ) -> TemplateEmail:
        return TemplateEmail(
            template="loginlink",
            to=[email],
            context=context,
        )
