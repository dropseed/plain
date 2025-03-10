from plain import models
from plain.utils import timezone


class CachedItemQuerySet(models.QuerySet):
    def expired(self):
        return self.filter(expires_at__lt=timezone.now())

    def unexpired(self):
        return self.filter(expires_at__gte=timezone.now())

    def forever(self):
        return self.filter(expires_at=None)


@models.register_model
class CachedItem(models.Model):
    key = models.CharField(max_length=255)
    value = models.JSONField(required=False, allow_null=True)
    expires_at = models.DateTimeField(required=False, allow_null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CachedItemQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=["expires_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["key"], name="plaincache_cacheditem_unique_key"
            ),
        ]

    def __str__(self) -> str:
        return self.key
