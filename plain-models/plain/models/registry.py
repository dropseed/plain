from __future__ import annotations

import functools
import warnings
from collections import defaultdict
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from plain.models.base import Model

M = TypeVar("M", bound="Model")


class ModelsRegistryNotReady(Exception):
    """The plain.models registry is not populated yet"""

    pass


class ModelsRegistry:
    def __init__(self) -> None:
        # Mapping of app labels => model names => model classes. Every time a
        # model is imported, ModelBase.__new__ calls packages.register_model which
        # creates an entry in all_models. All imported models are registered,
        # regardless of whether they're defined in an installed application
        # and whether the registry has been populated. Since it isn't possible
        # to reimport a module safely (it could reexecute initialization code)
        # all_models is never overridden or reset.
        self.all_models: defaultdict[str, dict[str, type[Model]]] = defaultdict(dict)

        # Maps ("package_label", "modelname") tuples to lists of functions to be
        # called when the corresponding model is ready. Used by this class's
        # `lazy_model_operation()` and `do_pending_operations()` methods.
        self._pending_operations: defaultdict[
            tuple[str, str], list[Callable[[type[Model]], None]]
        ] = defaultdict(list)

        self.ready: bool = False

    def check_ready(self) -> None:
        """Raise an exception if all models haven't been imported yet."""
        if not self.ready:
            raise ModelsRegistryNotReady("Models aren't loaded yet.")

    # This method is performance-critical at least for Plain's test suite.
    @functools.cache
    def get_models(self, *, package_label: str = "") -> list[type[Model]]:
        """
        Return a list of all installed models.

        By default, the following models aren't included:

        - auto-created models for many-to-many relations without
          an explicit intermediate table,

        Set the corresponding keyword argument to True to include such models.
        """

        self.check_ready()

        models = []

        # Get models for a single package
        if package_label:
            package_models = self.all_models[package_label]
            for model in package_models.values():
                models.append(model)
            return models

        # Get models for all packages
        for package_models in self.all_models.values():
            for model in package_models.values():
                models.append(model)

        return models

    def get_model(
        self,
        package_label: str,
        model_name: str | None = None,
        require_ready: bool = True,
    ) -> type[Model]:
        """
        Return the model matching the given package_label and model_name.

        As a shortcut, package_label may be in the form <package_label>.<model_name>.

        model_name is case-insensitive.

        Raise LookupError if no application exists with this label, or no
        model exists with this name in the application. Raise ValueError if
        called with a single argument that doesn't contain exactly one dot.
        """

        if require_ready:
            self.check_ready()

        if model_name is None:
            package_label, model_name = package_label.split(".")

        package_models = self.all_models[package_label]
        return package_models[model_name.lower()]

    def register_model(self, package_label: str, model: type[Model]) -> None:
        # Since this method is called when models are imported, it cannot
        # perform imports because of the risk of import loops. It mustn't
        # call get_package_config().
        model_name = model._meta.model_name
        app_models = self.all_models[package_label]
        if model_name in app_models:
            if (
                model.__name__ == app_models[model_name].__name__
                and model.__module__ == app_models[model_name].__module__
            ):
                warnings.warn(
                    f"Model '{package_label}.{model_name}' was already registered. Reloading models is not "
                    "advised as it can lead to inconsistencies, most notably with "
                    "related models.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            else:
                raise RuntimeError(
                    f"Conflicting '{model_name}' models in application '{package_label}': {app_models[model_name]} and {model}."
                )
        app_models[model_name] = model
        self.do_pending_operations(model)
        self.clear_cache()

    def _get_registered_model(self, package_label: str, model_name: str) -> type[Model]:
        """
        Similar to get_model(), but doesn't require that an app exists with
        the given package_label.

        It's safe to call this method at import time, even while the registry
        is being populated.
        """
        model = self.all_models[package_label].get(model_name.lower())
        if model is None:
            raise LookupError(f"Model '{package_label}.{model_name}' not registered.")
        return model

    def clear_cache(self) -> None:
        """
        Clear all internal caches, for methods that alter the app registry.

        This is mostly used in tests.
        """
        # Call expire cache on each model. This will purge
        # the relation tree and the fields cache.
        self.get_models.cache_clear()
        if self.ready:
            # Circumvent self.get_models() to prevent that the cache is refilled.
            # This particularly prevents that an empty value is cached while cloning.
            for package_models in self.all_models.values():
                for model in package_models.values():
                    model._meta._expire_cache()

    def lazy_model_operation(
        self, function: Callable[..., None], *model_keys: tuple[str, str]
    ) -> None:
        """
        Take a function and a number of ("package_label", "modelname") tuples, and
        when all the corresponding models have been imported and registered,
        call the function with the model classes as its arguments.

        The function passed to this method must accept exactly n models as
        arguments, where n=len(model_keys).
        """
        # Base case: no arguments, just execute the function.
        if not model_keys:
            function()
        # Recursive case: take the head of model_keys, wait for the
        # corresponding model class to be imported and registered, then apply
        # that argument to the supplied function. Pass the resulting partial
        # to lazy_model_operation() along with the remaining model args and
        # repeat until all models are loaded and all arguments are applied.
        else:
            next_model, *more_models = model_keys

            # This will be executed after the class corresponding to next_model
            # has been imported and registered. The `func` attribute provides
            # duck-type compatibility with partials.
            def apply_next_model(model: type[Model]) -> None:
                next_function = partial(apply_next_model.func, model)  # type: ignore[attr-defined]
                self.lazy_model_operation(next_function, *more_models)

            apply_next_model.func = function  # type: ignore[attr-defined]

            # If the model has already been imported and registered, partially
            # apply it to the function now. If not, add it to the list of
            # pending operations for the model, where it will be executed with
            # the model class as its sole argument once the model is ready.
            try:
                model_class = self._get_registered_model(*next_model)
            except LookupError:
                self._pending_operations[next_model].append(apply_next_model)
            else:
                apply_next_model(model_class)

    def do_pending_operations(self, model: type[Model]) -> None:
        """
        Take a newly-prepared model and pass it to each function waiting for
        it. This is called at the very end of Models.register_model().
        """
        key = model._meta.package_label, model._meta.model_name
        for function in self._pending_operations.pop(key, []):
            function(model)


models_registry = ModelsRegistry()


# Decorator to register a model (using the internal registry for the correct state).
def register_model(model_class: M) -> M:
    model_class._meta.models_registry.register_model(
        model_class._meta.package_label,
        model_class,  # type: ignore[arg-type]
    )
    return model_class
