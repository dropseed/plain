from typing import TypedDict

__all__ = ["ErrorSchema"]


class ErrorSchema(TypedDict):
    id: str
    message: str
    url: str
