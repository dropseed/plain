"""
Global Plain exception and warning classes.
"""

from __future__ import annotations

import operator
from collections.abc import Iterator
from typing import Any

from plain.utils.hashable import make_hashable

# MARK: Configuration and Package Registry


class PackageRegistryNotReady(Exception):
    """The plain.packages registry is not populated yet"""

    pass


class ImproperlyConfigured(Exception):
    """Plain is somehow improperly configured"""

    pass


# MARK: Validation

NON_FIELD_ERRORS = "__all__"


class ValidationError(Exception):
    """An error while validating data."""

    def __init__(
        self,
        message: str | list[Any] | dict[str, Any] | ValidationError,
        code: str | None = None,
        params: dict[str, Any] | None = None,
    ):
        """
        The `message` argument can be a single error, a list of errors, or a
        dictionary that maps field names to lists of errors. What we define as
        an "error" can be either a simple string or an instance of
        ValidationError with its message attribute set, and what we define as
        list or dictionary can be an actual `list` or `dict` or an instance
        of ValidationError with its `error_list` or `error_dict` attribute set.
        """
        super().__init__(message, code, params)

        if isinstance(message, ValidationError):
            if hasattr(message, "error_dict"):
                message = message.error_dict
            elif not hasattr(message, "message"):
                message = message.error_list
            else:
                message, code, params = message.message, message.code, message.params

        if isinstance(message, dict):
            self.error_dict = {}
            for field, messages in message.items():
                if not isinstance(messages, ValidationError):
                    messages = ValidationError(messages)
                self.error_dict[field] = messages.error_list

        elif isinstance(message, list):
            self.error_list = []
            for message in message:
                # Normalize plain strings to instances of ValidationError.
                if not isinstance(message, ValidationError):
                    message = ValidationError(message)
                if hasattr(message, "error_dict"):
                    self.error_list.extend(sum(message.error_dict.values(), []))
                else:
                    self.error_list.extend(message.error_list)

        else:
            self.message = message
            self.code = code
            self.params = params
            self.error_list = [self]

    @property
    def messages(self) -> list[str]:
        if hasattr(self, "error_dict"):
            return sum(dict(self).values(), [])  # type: ignore[arg-type]
        return list(self)

    def update_error_dict(
        self, error_dict: dict[str, list[ValidationError]]
    ) -> dict[str, list[ValidationError]]:
        if hasattr(self, "error_dict"):
            for field, error_list in self.error_dict.items():
                error_dict.setdefault(field, []).extend(error_list)
        else:
            error_dict.setdefault(NON_FIELD_ERRORS, []).extend(self.error_list)
        return error_dict

    def __iter__(self) -> Iterator[tuple[str, list[str]] | str]:
        if hasattr(self, "error_dict"):
            for field, errors in self.error_dict.items():
                yield field, list(ValidationError(errors))
        else:
            for error in self.error_list:
                message = error.message
                if error.params:
                    message %= error.params
                yield str(message)

    def __str__(self) -> str:
        if hasattr(self, "error_dict"):
            return repr(dict(self))  # type: ignore[arg-type]
        return repr(list(self))

    def __repr__(self) -> str:
        return f"ValidationError({self})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ValidationError):
            return NotImplemented
        return hash(self) == hash(other)

    def __hash__(self) -> int:
        if hasattr(self, "message"):
            return hash(
                (
                    self.message,
                    self.code,
                    make_hashable(self.params),
                )
            )
        if hasattr(self, "error_dict"):
            return hash(make_hashable(self.error_dict))
        return hash(tuple(sorted(self.error_list, key=operator.attrgetter("message"))))
