from plain.exceptions import ValidationError
from plain.http import BadRequestError400


class FormFieldMissingError(BadRequestError400):
    def __init__(self, field_name: str):
        self.field_name = field_name
        self.message = f'The "{self.field_name}" field is missing from the form data.'


__all__ = [
    "ValidationError",
    "FormFieldMissingError",
]
