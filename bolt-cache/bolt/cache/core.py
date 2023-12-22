from datetime import datetime, timedelta
from functools import cached_property

from bolt.utils import timezone

from .models import CachedItem


class Cached:
    def __init__(self, key):
        self.key = key

    @cached_property
    def _model_instance(self):
        try:
            return CachedItem.objects.get(key=self.key)
        except CachedItem.DoesNotExist:
            return None

    def reload(self):
        if hasattr(self, "_model_instance"):
            del self._model_instance

    def _is_expired(self):
        if not self._model_instance:
            return True

        if not self._model_instance.expires_at:
            return False

        return self._model_instance.expires_at < timezone.now()

    def exists(self):
        if self._model_instance is None:
            return False

        return not self._is_expired()

    @property
    def value(self):
        if not self.exists():
            return None

        return self._model_instance.value

    def set(self, value, expiration: datetime | timedelta | int | float | None = None):
        defaults = {
            "value": value,
        }

        if isinstance(expiration, int, float):
            defaults["expires_at"] = timezone.now() + timedelta(seconds=expiration)
        elif isinstance(expiration, timedelta):
            defaults["expires_at"] = timezone.now() + expiration
        elif isinstance(expiration, datetime):
            defaults["expires_at"] = expiration
        else:
            # Keep existing expires_at value or None
            pass

        item, _ = CachedItem.objects.update_or_create(key=self.key, defaults=defaults)

        self.reload()

        return item.value

    def delete(self):
        if not self._model_instance:
            # A no-op, but a return value you can use to know whether it did anything
            return False

        self._model_instance.delete()
        self.reload()
        return True
