from typing import TypedDict


class ErrorSchema(TypedDict):
    id: str
    message: str
    url: str | None
