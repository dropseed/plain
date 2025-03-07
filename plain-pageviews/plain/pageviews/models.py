import uuid

from plain import models


@models.register_model
class Pageview(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True)

    url = models.URLField(max_length=1024, db_index=True)
    timestamp = models.DateTimeField(db_index=True, auto_now_add=True)

    title = models.CharField(max_length=512, required=False)
    referrer = models.URLField(max_length=1024, required=False)

    user_id = models.CharField(max_length=255, db_index=True, required=False)
    session_key = models.CharField(max_length=255, db_index=True, required=False)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return self.url
