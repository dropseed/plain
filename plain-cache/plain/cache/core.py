from datetime import datetime, timedelta
from functools import cached_property

from opentelemetry import trace
from opentelemetry.semconv.attributes.db_attributes import (
    DB_NAMESPACE,
    DB_OPERATION_NAME,
    DB_SYSTEM_NAME,
)
from opentelemetry.trace import SpanKind

from plain.models import IntegrityError
from plain.utils import timezone

tracer = trace.get_tracer("plain.cache")


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
        with tracer.start_as_current_span(
            "cache.exists",
            kind=SpanKind.CLIENT,
            attributes={
                DB_SYSTEM_NAME: "plain.cache",
                DB_OPERATION_NAME: "get",
                DB_NAMESPACE: "cache",
                "cache.key": self.key,
            },
        ) as span:
            span.set_status(trace.StatusCode.OK)

            if self._model_instance is None:
                return False

            return not self._is_expired()

    @property
    def value(self):
        with tracer.start_as_current_span(
            "cache.get",
            kind=SpanKind.CLIENT,
            attributes={
                DB_SYSTEM_NAME: "plain.cache",
                DB_OPERATION_NAME: "get",
                DB_NAMESPACE: "cache",
                "cache.key": self.key,
            },
        ) as span:
            if self._model_instance and self._model_instance.expires_at:
                span.set_attribute(
                    "cache.item.expires_at", self._model_instance.expires_at.isoformat()
                )

            exists = self.exists()

            span.set_attribute("cache.hit", exists)
            span.set_status(trace.StatusCode.OK if exists else trace.StatusCode.UNSET)

            if not exists:
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
        if (
            "expires_at" in defaults
            and defaults["expires_at"]
            and not timezone.is_aware(defaults["expires_at"])
        ):
            defaults["expires_at"] = timezone.make_aware(defaults["expires_at"])

        with tracer.start_as_current_span(
            "cache.set",
            kind=SpanKind.CLIENT,
            attributes={
                DB_SYSTEM_NAME: "plain.cache",
                DB_OPERATION_NAME: "set",
                DB_NAMESPACE: "cache",
                "cache.key": self.key,
            },
        ) as span:
            if expires_at := defaults.get("expires_at"):
                span.set_attribute("cache.item.expires_at", expires_at.isoformat())

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
            span.set_status(trace.StatusCode.OK)
            return item.value

    def delete(self) -> bool:
        with tracer.start_as_current_span(
            "cache.delete",
            kind=SpanKind.CLIENT,
            attributes={
                DB_SYSTEM_NAME: "plain.cache",
                DB_OPERATION_NAME: "delete",
                DB_NAMESPACE: "cache",
                "cache.key": self.key,
            },
        ) as span:
            span.set_status(trace.StatusCode.OK)
            if not self._model_instance:
                # A no-op, but a return value you can use to know whether it did anything
                return False

            self._model_instance.delete()
            self.reload()
            return True
