from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any, TypeVar

T = TypeVar("T")


def deconstructible(
    *args: type[T], path: str | None = None
) -> Callable[[type[T]], type[T]] | type[T]:
    """
    Class decorator that allows the decorated class to be serialized
    by the migrations subsystem.

    The `path` kwarg specifies the import path.
    """

    def decorator(klass: type[T]) -> type[T]:
        def __new__(cls: type[T], *args: Any, **kwargs: Any) -> T:
            # We capture the arguments to make returning them trivial
            obj = super(klass, cls).__new__(cls)  # type: ignore[misc]
            obj._constructor_args = (args, kwargs)
            return obj

        def deconstruct(obj: Any) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
            """
            Return a 3-tuple of class import path, positional arguments,
            and keyword arguments.
            """
            # Fallback version
            if path and type(obj) is klass:
                module_name, _, name = path.rpartition(".")
            else:
                module_name = obj.__module__
                name = obj.__class__.__name__
            # Make sure it's actually there and not an inner class
            module = import_module(module_name)
            if not hasattr(module, name):
                raise ValueError(
                    f"Could not find object {name} in {module_name}.\n"
                    "Please note that you cannot serialize things like inner "
                    "classes. Please move the object into the main module "
                    "body to use migrations."
                )
            return (
                path
                if path and type(obj) is klass
                else f"{obj.__class__.__module__}.{name}",
                obj._constructor_args[0],
                obj._constructor_args[1],
            )

        setattr(klass, "__new__", staticmethod(__new__))
        setattr(klass, "deconstruct", deconstruct)

        return klass

    if not args:
        return decorator
    return decorator(*args)
