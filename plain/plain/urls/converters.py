from __future__ import annotations

import functools
import uuid
from typing import Any


class IntConverter:
    regex = "[0-9]+"

    def to_python(self, value: str) -> int:
        return int(value)

    def to_url(self, value: int) -> str:
        return str(value)


class StringConverter:
    regex = "[^/]+"

    def to_python(self, value: str) -> str:
        return value

    def to_url(self, value: str) -> str:
        return value


class UUIDConverter:
    regex = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

    def to_python(self, value: str) -> uuid.UUID:
        return uuid.UUID(value)

    def to_url(self, value: uuid.UUID) -> str:
        return str(value)


class SlugConverter(StringConverter):
    regex = "[-a-zA-Z0-9_]+"


class PathConverter(StringConverter):
    regex = ".+"


_DEFAULT_CONVERTERS = {
    "int": IntConverter(),
    "path": PathConverter(),
    "slug": SlugConverter(),
    "str": StringConverter(),
    "uuid": UUIDConverter(),
}


_REGISTERED_CONVERTERS: dict[str, Any] = {}


def register_converter(converter: type, type_name: str) -> None:
    _REGISTERED_CONVERTERS[type_name] = converter()
    _get_converters.cache_clear()


@functools.cache
def _get_converters() -> dict[str, Any]:
    return {**_DEFAULT_CONVERTERS, **_REGISTERED_CONVERTERS}


def _get_converter(raw_converter: str) -> Any:
    return _get_converters()[raw_converter]
