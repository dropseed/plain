from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain import forms
from plain.auth import get_user_model
from plain.email import TemplateEmail

from .links import generate_link_url

if TYPE_CHECKING:
    from plain.http import Request


class LoginLinkForm(forms.Form):
    email = forms.EmailField()
    next = forms.CharField(required=False)

    def maybe_send_link(
        self, request: Request, expires_in: int = 60 * 60
    ) -> int | None:
        user_model = get_user_model()
        email = self.cleaned_data["email"]
        try:
            user = user_model.query.get(email__iexact=email)
        except user_model.DoesNotExist:
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
