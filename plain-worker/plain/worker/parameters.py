import datetime

from plain.models import Model, models_registry


class JobParameter:
    """Base class for job parameter serialization/deserialization."""

    STR_PREFIX = None  # Subclasses should define this

    @classmethod
    def serialize(cls, value):
        """Return serialized string or None if can't handle this value."""
        return None

    @classmethod
    def deserialize(cls, data):
        """Return deserialized value or None if can't handle this data."""
        return None

    @classmethod
    def _extract_string_value(cls, data):
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
    def serialize(cls, value):
        if isinstance(value, Model):
            return f"{cls.STR_PREFIX}{value._meta.package_label}/{value._meta.model_name}/{value.id}"
        return None

    @classmethod
    def deserialize(cls, data):
        if value_part := cls._extract_string_value(data):
            try:
                parts = value_part.split("/")
                if len(parts) == 3 and all(parts):
                    package, model_name, obj_id = parts
                    model = models_registry.get_model(package, model_name)
                    return model.objects.get(id=obj_id)
            except (ValueError, Exception):
                pass
        return None


class DateParameter(JobParameter):
    """Handle date objects."""

    STR_PREFIX = "__plain://date/"

    @classmethod
    def serialize(cls, value):
        if isinstance(value, datetime.date) and not isinstance(
            value, datetime.datetime
        ):
            return f"{cls.STR_PREFIX}{value.isoformat()}"
        return None

    @classmethod
    def deserialize(cls, data):
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
    def serialize(cls, value):
        if isinstance(value, datetime.datetime):
            return f"{cls.STR_PREFIX}{value.isoformat()}"
        return None

    @classmethod
    def deserialize(cls, data):
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
    def serialize(cls, value):
        # Don't serialize new instances with legacy format
        return None

    @classmethod
    def deserialize(cls, data):
        if value_part := cls._extract_string_value(data):
            try:
                package, model, obj_id = value_part.split("/")
                model = models_registry.get_model(package, model)
                return model.objects.get(id=obj_id)
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
    def to_json(args, kwargs):
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
    def _serialize_value(value):
        """Serialize a single value using the registered parameter types."""
        # Try each parameter type to see if it can serialize this value
        for param_type in PARAMETER_TYPES:
            result = param_type.serialize(value)
            if result is not None:
                return result

        # If no parameter type can handle it, return as-is
        return value

    @staticmethod
    def from_json(data):
        args = []
        for arg in data["args"]:
            deserialized = JobParameters._deserialize_value(arg)
            args.append(deserialized)

        kwargs = {}
        for key, value in data["kwargs"].items():
            deserialized = JobParameters._deserialize_value(value)
            kwargs[key] = deserialized

        return args, kwargs

    @staticmethod
    def _deserialize_value(value):
        """Deserialize a single value using the registered parameter types."""
        # Try each parameter type to see if it can deserialize this value
        for param_type in PARAMETER_TYPES:
            result = param_type.deserialize(value)
            if result is not None:
                return result

        # If no parameter type can handle it, return as-is
        return value
