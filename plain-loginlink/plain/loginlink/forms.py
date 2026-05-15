from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.users.models import User

from plain import forms
from plain.email import TemplateEmail

from .links import generate_link_url

if TYPE_CHECKING:
    from plain.http import Request


class LoginLinkForm(forms.Form):
    email = forms.EmailField()
    next = forms.TextField(required=False)

    def maybe_send_link(
        self, request: Request, expires_in: int = 60 * 60
    ) -> int | None:
        email = self.cleaned_data["email"]
        try:
            user = User.query.get(email__iexact=email)
        except User.DoesNotExist:
            user = None

        if user:
            url = generate_link_url(
                request=request, user=user, email=email, expires_in=expires_in
            )

            if next_url := self.cleaned_data.get("next"):
                url += f"?next={next_url}"

            email = self.get_template_email(
                email=email,
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
