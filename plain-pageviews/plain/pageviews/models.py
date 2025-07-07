import uuid

from plain import models


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
    session_key = models.CharField(max_length=255, required=False)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp"]),
            models.Index(fields=["user_id"]),
            models.Index(fields=["session_key"]),
            models.Index(fields=["url"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["uuid"], name="plainpageviews_pageview_unique_uuid"
            ),
        ]

    def __str__(self):
        return self.url
