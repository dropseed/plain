from __future__ import annotations

import uuid
from datetime import datetime

from plain import models
from plain.runtime import settings
from plain.utils import timezone


@models.register_model
class Pageview(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4)

    # A full URL can be thousands of characters, but MySQL has a 3072-byte limit
    # on indexed columns (when using the default ``utf8mb4`` character set that
    # stores up to 4 bytes per character). The ``url`` field is indexed below,
    # so we keep the length at 768 characters (768 × 4 = 3072 bytes) to ensure
    # the index can be created on all supported database backends.
    url = models.URLField(max_length=768)
    timestamp = models.DateTimeField(auto_now_add=True)

    title = models.CharField(max_length=512, required=False)
    # Referrers may not always be valid URLs (e.g. `android-app://...`).
    # Use a plain CharField so we don't validate the scheme or format.
    referrer = models.CharField(max_length=1024, required=False)

    user_id = models.CharField(max_length=255, required=False)
    session_id = models.CharField(max_length=255, required=False)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp"]),
            models.Index(fields=["user_id"]),
            models.Index(fields=["session_id"]),
            models.Index(fields=["url"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["uuid"], name="plainpageviews_pageview_unique_uuid"
            ),
        ]

    def __str__(self) -> str:
        return self.url

    @classmethod
    def create_from_request(
        cls,
        request,
        *,
        url: str | None = None,
        title: str | None = None,
        referrer: str | None = None,
        timestamp: datetime | None = None,
    ) -> Pageview | None:
        """Create a pageview from a request object.

        Args:
            request: The HTTP request object
            url: Page URL (defaults to request.build_absolute_uri())
            title: Page title (defaults to empty string)
            referrer: Referring URL (defaults to Referer header)
            timestamp: Page visit time (defaults to current server time)

        Returns:
            Pageview instance or None if user is being impersonated
        """
        if getattr(request, "impersonator", None):
            return None

        if url is None:
            url = request.build_absolute_uri()

        if title is None:
            title = ""

        if referrer is None:
            referrer = request.headers.get("Referer", "")

        if timestamp is None:
            timestamp = timezone.now()

        if user := getattr(request, "user", None):
            user_id = user.id
        else:
            user_id = ""

        if session := getattr(request, "session", None):
            session_instance = session.model_instance
            session_id = str(session_instance.id) if session_instance else ""

            if settings.PAGEVIEWS_ASSOCIATE_ANONYMOUS_SESSIONS:
                if not user_id:
                    if not session_id:
                        # Make sure we have a key to use
                        session.create()
                        session_instance = session.model_instance
                        session_id = (
                            str(session_instance.id) if session_instance else ""
                        )

                    # The user hasn't logged in yet but might later. When they do log in,
                    # the session key itself will be cycled (session fixation attacks),
                    # so we'll store the anonymous session id in the data which will be preserved
                    # when the key cycles, then remove it immediately after.
                    session["pageviews_anonymous_session_id"] = session_id
                elif user_id and "pageviews_anonymous_session_id" in session:
                    # Associate the previously anonymous pageviews with the user
                    cls.query.filter(
                        user_id="",
                        session_id=session["pageviews_anonymous_session_id"],
                    ).update(user_id=user_id)

                    # Remove it so we don't keep trying to associate it
                    del session["pageviews_anonymous_session_id"]
        else:
            session_id = ""

        return cls.query.create(
            user_id=user_id,
            session_id=session_id,
            url=url,
            title=title,
            referrer=referrer,
            timestamp=timestamp,
        )
