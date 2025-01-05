import uuid

from plain import models


class Pageview(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)

    url = models.URLField(max_length=255, db_index=True)
    timestamp = models.DateTimeField(db_index=True, auto_now_add=True)

    title = models.CharField(max_length=255, blank=True)
    referrer = models.URLField(max_length=255, blank=True)

    user_id = models.CharField(max_length=255, db_index=True, blank=True)
    session_key = models.CharField(max_length=255, db_index=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return self.url