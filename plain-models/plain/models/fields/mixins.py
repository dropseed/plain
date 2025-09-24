from plain.preflight import PreflightResult

NOT_PROVIDED = object()


class FieldCacheMixin:
    """Provide an API for working with the model's fields value cache."""

    def get_cache_name(self):
        raise NotImplementedError

    def get_cached_value(self, instance, default=NOT_PROVIDED):
        cache_name = self.get_cache_name()
        try:
            return instance._state.fields_cache[cache_name]
        except KeyError:
            if default is NOT_PROVIDED:
                raise
            return default

    def is_cached(self, instance):
        return self.get_cache_name() in instance._state.fields_cache

    def set_cached_value(self, instance, value):
        instance._state.fields_cache[self.get_cache_name()] = value

    def delete_cached_value(self, instance):
        del instance._state.fields_cache[self.get_cache_name()]


class CheckFieldDefaultMixin:
    _default_hint = ("<valid default>", "<invalid default>")

    def _check_default(self):
        if (
            self.has_default()
            and self.default is not None
            and not callable(self.default)
        ):
            return [
                PreflightResult(
                    f"{self.__class__.__name__} default should be a callable instead of an instance "
                    "so that it's not shared between all field instances.",
                    hint=(
                        "Use a callable instead, e.g., use `{}` instead of "
                        "`{}`.".format(*self._default_hint)
                    ),
                    obj=self,
                    id="fields.E010",
                    warning=True,
                )
            ]
        else:
            return []

    def preflight(self, **kwargs):
        errors = super().preflight(**kwargs)
        errors.extend(self._check_default())
        return errors
