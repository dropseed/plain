from plain.exceptions import ValidationError


class FormFieldMissingError(Exception):
    pass


__all__ = [
    "ValidationError",
    "FormFieldMissingError",
]
