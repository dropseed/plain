from __future__ import annotations

from typing import Any, cast

# MARK: Database Query Exceptions


class EmptyResultSet(Exception):
    """A database query predicate is impossible."""

    pass


class FullResultSet(Exception):
    """A database query predicate is matches everything."""

    pass


# MARK: Model and Field Errors


class FieldDoesNotExist(Exception):
    """The requested model field does not exist"""

    pass


class FieldError(Exception):
    """Some kind of problem with a model field."""

    pass


class ObjectDoesNotExist(Exception):
    """The requested object does not exist"""

    pass


class MultipleObjectsReturned(Exception):
    """The query returned multiple objects when only one was expected."""

    pass


# MARK: Model Exception Descriptors


class DoesNotExistDescriptor:
    """Descriptor that creates a unique DoesNotExist exception class per model."""

    def __init__(self) -> None:
        self._exceptions_by_class: dict[type, type[ObjectDoesNotExist]] = {}

    def __get__(self, instance: Any, owner: type | None) -> type[ObjectDoesNotExist]:
        if owner is None:
            return ObjectDoesNotExist  # Return base class as fallback

        # Create a unique exception class for this model if we haven't already
        if owner not in self._exceptions_by_class:
            # type() returns a subclass of ObjectDoesNotExist
            exc_class: type[ObjectDoesNotExist] = cast(
                type[ObjectDoesNotExist],
                type(
                    "DoesNotExist",
                    (ObjectDoesNotExist,),
                    {
                        "__module__": owner.__module__,
                        "__qualname__": f"{owner.__qualname__}.DoesNotExist",
                    },
                ),
            )
            self._exceptions_by_class[owner] = exc_class

        return self._exceptions_by_class[owner]

    def __set__(self, instance: Any, value: Any) -> None:
        raise AttributeError("Cannot set DoesNotExist")


class MultipleObjectsReturnedDescriptor:
    """Descriptor that creates a unique MultipleObjectsReturned exception class per model."""

    def __init__(self) -> None:
        self._exceptions_by_class: dict[type, type[MultipleObjectsReturned]] = {}

    def __get__(
        self, instance: Any, owner: type | None
    ) -> type[MultipleObjectsReturned]:
        if owner is None:
            return MultipleObjectsReturned  # Return base class as fallback

        # Create a unique exception class for this model if we haven't already
        if owner not in self._exceptions_by_class:
            # type() returns a subclass of MultipleObjectsReturned
            exc_class = cast(
                type[MultipleObjectsReturned],
                type(
                    "MultipleObjectsReturned",
                    (MultipleObjectsReturned,),
                    {
                        "__module__": owner.__module__,
                        "__qualname__": f"{owner.__qualname__}.MultipleObjectsReturned",
                    },
                ),
            )
            self._exceptions_by_class[owner] = exc_class

        return self._exceptions_by_class[owner]

    def __set__(self, instance: Any, value: Any) -> None:
        raise AttributeError("Cannot set MultipleObjectsReturned")
