from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper

F = TypeVar("F", bound=Callable[..., Any])

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
            exc_class = type(
                "DoesNotExist",
                (ObjectDoesNotExist,),
                {
                    "__module__": owner.__module__,
                    "__qualname__": f"{owner.__qualname__}.DoesNotExist",
                },
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
            exc_class = type(
                "MultipleObjectsReturned",
                (MultipleObjectsReturned,),
                {
                    "__module__": owner.__module__,
                    "__qualname__": f"{owner.__qualname__}.MultipleObjectsReturned",
                },
            )
            self._exceptions_by_class[owner] = exc_class

        return self._exceptions_by_class[owner]

    def __set__(self, instance: Any, value: Any) -> None:
        raise AttributeError("Cannot set MultipleObjectsReturned")


# MARK: Database Exceptions (PEP-249)


class Error(Exception):
    pass


class InterfaceError(Error):
    pass


class DatabaseError(Error):
    pass


class DataError(DatabaseError):
    pass


class OperationalError(DatabaseError):
    pass


class IntegrityError(DatabaseError):
    pass


class InternalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


class NotSupportedError(DatabaseError):
    pass


class ConnectionDoesNotExist(Exception):
    pass


class DatabaseErrorWrapper:
    """
    Context manager and decorator that reraises backend-specific database
    exceptions using Plain's common wrappers.
    """

    def __init__(self, wrapper: BaseDatabaseWrapper) -> None:
        """
        wrapper is a database wrapper.

        It must have a Database attribute defining PEP-249 exceptions.
        """
        self.wrapper = wrapper

    def __enter__(self) -> None:
        pass

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        if exc_type is None:
            return
        for plain_exc_type in (
            DataError,
            OperationalError,
            IntegrityError,
            InternalError,
            ProgrammingError,
            NotSupportedError,
            DatabaseError,
            InterfaceError,
            Error,
        ):
            db_exc_type = getattr(self.wrapper.Database, plain_exc_type.__name__)
            if issubclass(exc_type, db_exc_type):
                plain_exc_value = (
                    plain_exc_type(*exc_value.args) if exc_value else plain_exc_type()
                )
                # Only set the 'errors_occurred' flag for errors that may make
                # the connection unusable.
                if plain_exc_type not in (DataError, IntegrityError):
                    self.wrapper.errors_occurred = True
                raise plain_exc_value.with_traceback(traceback) from exc_value

    def __call__(self, func: F) -> F:
        # Note that we are intentionally not using @wraps here for performance
        # reasons. Refs #21109.
        def inner(*args: Any, **kwargs: Any) -> Any:
            with self:
                return func(*args, **kwargs)

        return inner  # type: ignore[return-value]
