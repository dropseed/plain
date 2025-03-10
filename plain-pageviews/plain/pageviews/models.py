import uuid

from plain import models


@models.register_model
class Pageview(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4)

    url = models.URLField(max_length=1024)
    timestamp = models.DateTimeField(auto_now_add=True)

    title = models.CharField(max_length=512, required=False)
    referrer = models.URLField(max_length=1024, required=False)

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
