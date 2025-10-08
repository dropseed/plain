from __future__ import annotations

import datetime
from typing import Any

from plain.models import Model, models_registry


class JobParameter:
    """Base class for job parameter serialization/deserialization."""

    STR_PREFIX: str | None = None  # Subclasses should define this

    @classmethod
    def serialize(cls, value: Any) -> str | None:
        """Return serialized string or None if can't handle this value."""
        return None

    @classmethod
    def deserialize(cls, data: Any) -> Any:
        """Return deserialized value or None if can't handle this data."""
        return None

    @classmethod
    def _extract_string_value(cls, data: Any) -> str | None:
        """Extract value from string with prefix, return None if invalid format."""
        if not isinstance(data, str) or not cls.STR_PREFIX:
            return None
        if not data.startswith(cls.STR_PREFIX) or len(data) <= len(cls.STR_PREFIX):
            return None
        return data[len(cls.STR_PREFIX) :]


class ModelParameter(JobParameter):
    """Handle Plain model instances using a new string format."""

    STR_PREFIX = "__plain://model/"

    @classmethod
    def serialize(cls, value: Any) -> str | None:
        if isinstance(value, Model):
            return f"{cls.STR_PREFIX}{value.model_options.package_label}/{value.model_options.model_name}/{value.id}"
        return None

    @classmethod
    def deserialize(cls, data: Any) -> Model | None:
        if value_part := cls._extract_string_value(data):
            try:
                parts = value_part.split("/")
                if len(parts) == 3 and all(parts):
                    package, model_name, obj_id = parts
                    model = models_registry.get_model(package, model_name)
                    return model.query.get(id=obj_id)
            except (ValueError, Exception):
                pass
        return None


class DateParameter(JobParameter):
    """Handle date objects."""

    STR_PREFIX = "__plain://date/"

    @classmethod
    def serialize(cls, value: Any) -> str | None:
        if isinstance(value, datetime.date) and not isinstance(
            value, datetime.datetime
        ):
            return f"{cls.STR_PREFIX}{value.isoformat()}"
        return None

    @classmethod
    def deserialize(cls, data: Any) -> datetime.date | None:
        if value_part := cls._extract_string_value(data):
            try:
                return datetime.date.fromisoformat(value_part)
            except ValueError:
                pass
        return None


class DateTimeParameter(JobParameter):
    """Handle datetime objects."""

    STR_PREFIX = "__plain://datetime/"

    @classmethod
    def serialize(cls, value: Any) -> str | None:
        if isinstance(value, datetime.datetime):
            return f"{cls.STR_PREFIX}{value.isoformat()}"
        return None

    @classmethod
    def deserialize(cls, data: Any) -> datetime.datetime | None:
        if value_part := cls._extract_string_value(data):
            try:
                return datetime.datetime.fromisoformat(value_part)
            except ValueError:
                pass
        return None


class LegacyModelParameter(JobParameter):
    """Legacy model parameter handling for backwards compatibility."""

    STR_PREFIX = "gid://"

    @classmethod
    def serialize(cls, value: Any) -> str | None:
        # Don't serialize new instances with legacy format
        return None

    @classmethod
    def deserialize(cls, data: Any) -> Model | None:
        if value_part := cls._extract_string_value(data):
            try:
                package, model, obj_id = value_part.split("/")
                model = models_registry.get_model(package, model)
                return model.query.get(id=obj_id)
            except (ValueError, Exception):
                pass
        return None


# Registry of parameter types to check in order
# The order matters - more specific types should come first
# DateTimeParameter must come before DateParameter since datetime is a subclass of date
# LegacyModelParameter is last since it only handles deserialization
PARAMETER_TYPES = [
    ModelParameter,
    DateTimeParameter,
    DateParameter,
    LegacyModelParameter,
]


class JobParameters:
    """
    Main interface for serializing and deserializing job parameters.
    Uses the registered parameter types to handle different value types.
    """

    @staticmethod
    def to_json(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
        serialized_args = []
        for arg in args:
            serialized = JobParameters._serialize_value(arg)
            serialized_args.append(serialized)

        serialized_kwargs = {}
        for key, value in kwargs.items():
            serialized = JobParameters._serialize_value(value)
            serialized_kwargs[key] = serialized

        return {"args": serialized_args, "kwargs": serialized_kwargs}

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        """Serialize a single value using the registered parameter types."""
        # Try each parameter type to see if it can serialize this value
        for param_type in PARAMETER_TYPES:
            result = param_type.serialize(value)
            if result is not None:
                return result

        # If no parameter type can handle it, return as-is
        return value

    @staticmethod
    def from_json(data: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
        args = []
        for arg in data["args"]:
            deserialized = JobParameters._deserialize_value(arg)
            args.append(deserialized)

        kwargs = {}
        for key, value in data["kwargs"].items():
            deserialized = JobParameters._deserialize_value(value)
            kwargs[key] = deserialized

        return tuple(args), kwargs

    @staticmethod
    def _deserialize_value(value: Any) -> Any:
        """Deserialize a single value using the registered parameter types."""
        # Try each parameter type to see if it can deserialize this value
        for param_type in PARAMETER_TYPES:
            result = param_type.deserialize(value)
            if result is not None:
                return result

        # If no parameter type can handle it, return as-is
        return value
