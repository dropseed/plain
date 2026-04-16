from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from plain import postgres
from plain.postgres import types

if TYPE_CHECKING:
    from plain.http import Request

__all__ = ["NotFoundLog", "Redirect", "RedirectLog"]


@postgres.register_model
class Redirect(postgres.Model):
    from_pattern: str = types.TextField(max_length=255)
    to_pattern: str = types.TextField(max_length=255)
    http_status: int = types.SmallIntegerField(
        default=301
    )  # Default to permanent - could be choices?
    created_at: datetime = types.DateTimeField(create_now=True)
    updated_at: datetime = types.DateTimeField(create_now=True, update_now=True)
    order: int = types.SmallIntegerField(default=0)
    enabled: bool = types.BooleanField(default=True)
    is_regex: bool = types.BooleanField(default=False)

    # query params?
    # logged in or not? auth not required necessarily...
    # headers?

    query: postgres.QuerySet[Redirect] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["order", "-created_at"],
        indexes=[
            postgres.Index(
                name="plainredirection_redirect_order_idx", fields=["order"]
            ),
            postgres.Index(
                name="plainredirection_redirect_created_at_idx", fields=["created_at"]
            ),
        ],
        constraints=[
            postgres.UniqueConstraint(
                fields=["from_pattern"],
                name="plainredirects_redirect_unique_from_pattern",
            ),
            postgres.CheckConstraint(
                check=postgres.Q(http_status__gte=0),
                name="plainredirection_redirect_http_status_check",
            ),
            postgres.CheckConstraint(
                check=postgres.Q(order__gte=0),
                name="plainredirection_redirect_order_check",
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


@postgres.register_model
class RedirectLog(postgres.Model):
    redirect: Redirect = types.ForeignKeyField(Redirect, on_delete=postgres.CASCADE)

    # The actuals that were used to redirect
    from_url: str = types.URLField(max_length=512)
    to_url: str = types.URLField(max_length=512)
    http_status: int = types.SmallIntegerField(default=301)

    # Request metadata
    ip_address: str = types.GenericIPAddressField()
    user_agent: str = types.TextField(required=False, max_length=512)
    referrer: str = types.TextField(required=False, max_length=512)

    created_at: datetime = types.DateTimeField(create_now=True)

    query: postgres.QuerySet[RedirectLog] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["-created_at"],
        indexes=[
            postgres.Index(
                name="plainredirection_redirectlog_created_at_idx",
                fields=["created_at"],
            ),
            postgres.Index(
                name="plainredirection_redirectlog_redirect_id_idx",
                fields=["redirect"],
            ),
        ],
        constraints=[
            postgres.CheckConstraint(
                check=postgres.Q(http_status__gte=0),
                name="plainredirection_redirectlog_http_status_check",
            ),
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
            ip_address=request.client_ip,
            user_agent=request.headers.get("User-Agent", ""),
            referrer=request.headers.get("Referer", ""),
        )


@postgres.register_model
class NotFoundLog(postgres.Model):
    url: str = types.URLField(max_length=512)

    # Request metadata
    ip_address: str = types.GenericIPAddressField()
    user_agent: str = types.TextField(required=False, max_length=512)
    referrer: str = types.TextField(required=False, max_length=512)

    created_at: datetime = types.DateTimeField(create_now=True)

    query: postgres.QuerySet[NotFoundLog] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["-created_at"],
        indexes=[
            postgres.Index(
                name="plainredirection_notfoundlog_created_at_idx",
                fields=["created_at"],
            ),
        ],
    )

    @classmethod
    def from_request(cls, request: Request) -> NotFoundLog:
        return cls.query.create(
            url=request.build_absolute_uri(),
            ip_address=request.client_ip,
            user_agent=request.headers.get("User-Agent", ""),
            referrer=request.headers.get("Referer", ""),
        )
