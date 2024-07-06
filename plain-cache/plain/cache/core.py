from datetime import datetime, timedelta
from functools import cached_property

from plain.models import IntegrityError
from plain.utils import timezone


class Cached:
    """Store and retrieve cached items."""

    def __init__(self, key: str) -> None:
        self.key = key

        # So we can import Cached in __init__.py
        # without getting the packages not ready error...
        from .models import CachedItem

        self._model_class = CachedItem

    @cached_property
    def _model_instance(self):
        try:
            return self._model_class.objects.get(key=self.key)
        except self._model_class.DoesNotExist:
            return None

    def reload(self) -> None:
        if hasattr(self, "_model_instance"):
            del self._model_instance

    def _is_expired(self):
        if not self._model_instance:
            return True

        if not self._model_instance.expires_at:
            return False

        return self._model_instance.expires_at < timezone.now()

    def exists(self) -> bool:
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

        if isinstance(expiration, int | float):
            defaults["expires_at"] = timezone.now() + timedelta(seconds=expiration)
        elif isinstance(expiration, timedelta):
            defaults["expires_at"] = timezone.now() + expiration
        elif isinstance(expiration, datetime):
            defaults["expires_at"] = expiration
        else:
            # Keep existing expires_at value or None
            pass

        # Make sure expires_at is timezone aware
        if defaults["expires_at"] and not timezone.is_aware(defaults["expires_at"]):
            defaults["expires_at"] = timezone.make_aware(defaults["expires_at"])

        try:
            item, _ = self._model_class.objects.update_or_create(
                key=self.key, defaults=defaults
            )
        except IntegrityError:
            # Most likely a race condition in creating the item,
            # so trying again should do an update
            item, _ = self._model_class.objects.update_or_create(
                key=self.key, defaults=defaults
            )

        self.reload()
        return item.value

    def delete(self) -> bool:
        if not self._model_instance:
            # A no-op, but a return value you can use to know whether it did anything
            return False

        self._model_instance.delete()
        self.reload()
        return True
