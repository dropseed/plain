from __future__ import annotations

from typing import Any

NOT_PROVIDED = object()


class FieldCacheMixin:
    """Provide an API for working with the model's fields value cache."""

    def get_cache_name(self) -> str:
        raise NotImplementedError

    def get_cached_value(self, instance: Any, default: Any = NOT_PROVIDED) -> Any:
        cache_name = self.get_cache_name()
        try:
            return instance._state.fields_cache[cache_name]
        except KeyError:
            if default is NOT_PROVIDED:
                raise
            return default

    def is_cached(self, instance: Any) -> bool:
        return self.get_cache_name() in instance._state.fields_cache

    def set_cached_value(self, instance: Any, value: Any) -> None:
        instance._state.fields_cache[self.get_cache_name()] = value

    def delete_cached_value(self, instance: Any) -> None:
        del instance._state.fields_cache[self.get_cache_name()]
