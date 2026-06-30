from __future__ import annotations

import re
from typing import TYPE_CHECKING

import psycopg

from plain import postgres
from plain.exceptions import ValidationError
from plain.postgres import transaction, types
from plain.postgres.expressions import F
from plain.utils import timezone

if TYPE_CHECKING:
    from datetime import datetime

    from plain.http import Request

__all__ = ["NotFoundLog", "Redirect", "RedirectLog"]


@postgres.register_model
class Redirect(postgres.Model):
    from_pattern = types.TextField(max_length=255)
    to_pattern = types.TextField(max_length=255)
    http_status = types.SmallIntegerField(
        default=301
    )  # Default to permanent - could be choices?
    created_at = types.DateTimeField(create_now=True)
    updated_at = types.DateTimeField(create_now=True, update_now=True)
    order = types.SmallIntegerField(default=0)
    enabled = types.BooleanField(default=True)
    is_regex = types.BooleanField(default=False)

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
    redirect = types.ForeignKeyField(Redirect, on_delete=postgres.CASCADE)

    # The actuals that were used to redirect
    from_url = types.URLField(max_length=512)
    to_url = types.URLField(max_length=512)
    http_status = types.SmallIntegerField(default=301)

    # Request metadata
    ip_address = types.GenericIPAddressField()
    user_agent = types.TextField(required=False, max_length=512)
    referrer = types.TextField(required=False, max_length=512)

    created_at = types.DateTimeField(create_now=True)

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
    # One row per URL -- repeat 404s for the same URL increment `count` instead
    # of inserting a new row, so the table tracks distinct broken URLs rather
    # than every individual crawler hit.
    #
    # url is a TextField, not a URLField: it captures whatever URL was requested
    # (often by crawlers probing odd paths, and on non-dotted hosts like
    # localhost), so URL-format validation would only get in the way.
    url = types.TextField(max_length=512)
    count = types.IntegerField(default=1)

    # Metadata from the most recent hit
    ip_address = types.GenericIPAddressField()
    user_agent = types.TextField(required=False, max_length=512)
    referrer = types.TextField(required=False, max_length=512)

    # Both set explicitly on insert and refreshed by _increment, so last_seen
    # is plain create_now (not update_now) -- nothing does an instance .update()
    # that would need auto-stamping.
    first_seen = types.DateTimeField(create_now=True)
    last_seen = types.DateTimeField(create_now=True)

    query: postgres.QuerySet[NotFoundLog] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["-last_seen"],
        indexes=[
            postgres.Index(
                name="plainredirection_notfoundlog_last_seen_idx",
                fields=["last_seen"],
            ),
        ],
        constraints=[
            postgres.UniqueConstraint(
                fields=["url"],
                name="plainredirection_notfoundlog_unique_url",
            ),
            postgres.CheckConstraint(
                check=postgres.Q(count__gte=1),
                name="plainredirection_notfoundlog_count_check",
            ),
        ],
    )

    def __str__(self) -> str:
        return f"{self.url} ({self.count})"

    @classmethod
    def from_request(cls, request: Request) -> None:
        """Record a 404 for this URL, collapsing repeats into a single row.

        Crawlers hammer the same handful of dead URLs, so nearly every 404 is a
        repeat -- try the increment first, and only insert on the first sighting.
        """
        url = request.build_absolute_uri()
        ip_address = request.client_ip
        user_agent = request.headers.get("User-Agent", "")
        referrer = request.headers.get("Referer", "")
        now = timezone.now()

        if cls._increment(url, ip_address, user_agent, referrer, now):
            return

        # First time we've seen this URL. A concurrent request for the same new
        # URL can race us here; the unique constraint turns the loser's insert
        # into an error, which we resolve by falling back to the increment.
        try:
            with transaction.atomic():
                cls.query.create(
                    url=url,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    referrer=referrer,
                    first_seen=now,
                    last_seen=now,
                )
        except (psycopg.IntegrityError, ValidationError):
            cls._increment(url, ip_address, user_agent, referrer, now)

    @classmethod
    def _increment(
        cls,
        url: str,
        ip_address: str,
        user_agent: str,
        referrer: str,
        now: datetime,
    ) -> int:
        """Bump an existing URL's counter and refresh its latest-hit metadata.

        Returns the number of rows updated (0 if the URL hasn't been seen yet).
        """
        return cls.query.filter(url=url).update(
            count=F("count") + 1,
            ip_address=ip_address,
            user_agent=user_agent,
            referrer=referrer,
            last_seen=now,
        )
