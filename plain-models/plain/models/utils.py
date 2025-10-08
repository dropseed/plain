from __future__ import annotations

import functools
from collections import namedtuple
from collections.abc import Generator
from typing import Any


def make_model_tuple(model: Any) -> tuple[str, str]:
    """
    Take a model or a string of the form "package_label.ModelName" and return a
    corresponding ("package_label", "modelname") tuple. If a tuple is passed in,
    assume it's a valid model tuple already and return it unchanged.
    """
    try:
        if isinstance(model, tuple):
            model_tuple = model
        elif isinstance(model, str):
            package_label, model_name = model.split(".")
            model_tuple = package_label, model_name.lower()
        else:
            model_tuple = (
                model.model_options.package_label,
                model.model_options.model_name,
            )
        assert len(model_tuple) == 2
        return model_tuple
    except (ValueError, AssertionError):
        raise ValueError(
            f"Invalid model reference '{model}'. String model references "
            "must be of the form 'package_label.ModelName'."
        )


def resolve_callables(
    mapping: dict[str, Any],
) -> Generator[tuple[str, Any], None, None]:
    """
    Generate key/value pairs for the given mapping where the values are
    evaluated if they're callable.
    """
    for k, v in mapping.items():
        yield k, v() if callable(v) else v


def unpickle_named_row(
    names: tuple[str, ...], values: tuple[Any, ...]
) -> tuple[Any, ...]:
    return create_namedtuple_class(*names)(*values)


@functools.lru_cache
def create_namedtuple_class(*names: str) -> type[tuple[Any, ...]]:
    # Cache type() with @lru_cache since it's too slow to be called for every
    # QuerySet evaluation.
    def __reduce__(self: Any) -> tuple[Any, tuple[tuple[str, ...], tuple[Any, ...]]]:
        return unpickle_named_row, (names, tuple(self))

    return type(
        "Row",
        (namedtuple("Row", names),),
        {"__reduce__": __reduce__, "__slots__": ()},
    )
