from plain.exceptions import ValidationError


class FormFieldMissingError(Exception):
    def __init__(self, *, field_name, message):
        self.field_name = field_name
        self.message = message


__all__ = [
    "ValidationError",
    "FormFieldMissingError",
]
