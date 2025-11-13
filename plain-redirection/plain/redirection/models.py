from __future__ import annotations

import re
from typing import TYPE_CHECKING

from plain.models import (
    CASCADE,
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKey,
    GenericIPAddressField,
    Index,
    Model,
    Options,
    PositiveSmallIntegerField,
    UniqueConstraint,
    URLField,
    register_model,
)

if TYPE_CHECKING:
    from plain.http import Request


def _get_client_ip(request: Request) -> str | None:
    if x_forwarded_for := request.headers.get("X-Forwarded-For"):
        return x_forwarded_for.split(",")[0].strip()
    else:
        return request.meta.get("REMOTE_ADDR")


@register_model
class Redirect(Model):
    from_pattern = CharField(max_length=255)
    to_pattern = CharField(max_length=255)
    http_status = PositiveSmallIntegerField(
        default=301  # Default to permanent - could be choices?
    )
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    order = PositiveSmallIntegerField(default=0)
    enabled = BooleanField(default=True)
    is_regex = BooleanField(default=False)

    # query params?
    # logged in or not? auth not required necessarily...
    # headers?

    model_options = Options(
        ordering=["order", "-created_at"],
        indexes=[
            Index(fields=["order"]),
            Index(fields=["created_at"]),
        ],
        constraints=[
            UniqueConstraint(
                fields=["from_pattern"],
                name="plainredirects_redirect_unique_from_pattern",
            ),
        ],
    )

    def __str__(self) -> str:
        return f"{self.from_pattern}"

    def matches_request(self, request: Request) -> bool:
        """
        Decide whether a request matches this Redirect,
        automatically checking whether the pattern is path based or full URL based.
        """

        if self.from_pattern.startswith("http"):
            # Full url with query params
            url = request.build_absolute_uri()
        else:
            # Doesn't include query params or host
            url = request.path

        if self.is_regex:
            return bool(re.match(self.from_pattern, url))
        else:
            return url == self.from_pattern

    def get_redirect_url(self, request: Request) -> str:
        if not self.is_regex:
            return self.to_pattern

        # Replace any regex groups in the to_pattern
        if self.from_pattern.startswith("http"):
            url = request.build_absolute_uri()
        else:
            url = request.path

        return re.sub(self.from_pattern, self.to_pattern, url)


@register_model
class RedirectLog(Model):
    redirect = ForeignKey(Redirect, on_delete=CASCADE)

    # The actuals that were used to redirect
    from_url = URLField(max_length=512)
    to_url = URLField(max_length=512)
    http_status = PositiveSmallIntegerField(default=301)

    # Request metadata
    ip_address = GenericIPAddressField()
    user_agent = CharField(max_length=512, default="")
    referrer = CharField(max_length=512, default="")

    created_at = DateTimeField(auto_now_add=True)

    model_options = Options(
        ordering=["-created_at"],
        indexes=[
            Index(fields=["created_at"]),
        ],
    )

    @classmethod
    def from_redirect(cls, redirect: Redirect, request: Request) -> RedirectLog:
        from_url = request.build_absolute_uri()
        to_url = redirect.get_redirect_url(request)

        if not to_url.startswith("http"):
            to_url = request.build_absolute_uri(to_url)

        if from_url == to_url:
            raise ValueError("Redirecting to the same URL")

        return cls.query.create(
            redirect=redirect,
            from_url=from_url,
            to_url=to_url,
            http_status=redirect.http_status,
            ip_address=_get_client_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
            referrer=request.headers.get("Referer", ""),
        )


@register_model
class NotFoundLog(Model):
    url = URLField(max_length=512)

    # Request metadata
    ip_address = GenericIPAddressField()
    user_agent = CharField(max_length=512, allow_null=True)
    referrer = CharField(max_length=512, allow_null=True)

    created_at = DateTimeField(auto_now_add=True)

    model_options = Options(
        ordering=["-created_at"],
        indexes=[
            Index(fields=["created_at"]),
        ],
    )

    @classmethod
    def from_request(cls, request: Request) -> NotFoundLog:
        return cls.query.create(
            url=request.build_absolute_uri(),
            ip_address=_get_client_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
            referrer=request.headers.get("Referer", ""),
        )
