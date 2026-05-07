from typing import NotRequired, TypedDict

__all__ = ["ErrorSchema", "FieldError"]


class FieldError(TypedDict):
    field: str
    message: str


class ErrorSchema(TypedDict):
    id: str
    message: str
    errors: NotRequired[list[FieldError]]
