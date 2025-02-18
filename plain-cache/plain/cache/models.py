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
    key = models.CharField(max_length=255, unique=True)
    value = models.JSONField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CachedItemQuerySet.as_manager()

    def __str__(self) -> str:
        return self.key
