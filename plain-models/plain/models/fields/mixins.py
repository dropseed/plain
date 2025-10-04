from __future__ import annotations

from typing import Any

from plain.preflight import PreflightResult

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


class CheckFieldDefaultMixin:
    _default_fix = ("<valid default>", "<invalid default>")

    def _check_default(self) -> list[PreflightResult]:  # type: ignore[misc]
        if (
            self.has_default()
            and self.default is not None
            and not callable(self.default)
        ):
            return [
                PreflightResult(
                    fix=(
                        f"{self.__class__.__name__} default should be a callable instead of an instance "
                        "so that it's not shared between all field instances. "
                        "Use a callable instead, e.g., use `{}` instead of "
                        "`{}`.".format(*self._default_fix)
                    ),
                    obj=self,
                    id="fields.invalid_choice_mixin_default",
                    warning=True,
                )
            ]
        else:
            return []

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:  # type: ignore[misc]
        errors = super().preflight(**kwargs)  # type: ignore[misc]
        errors.extend(self._check_default())
        return errors
