"""The `MCPResource` base class. Subclass, set `uri` (or `uri_template`), and implement `read()`."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, get_type_hints

if TYPE_CHECKING:
    from .views import MCPView


class MCPResource(ABC):
    """Base class for MCP resources.

    Resources are addressable data sources identified by a URI that
    clients can list and read. Metadata comes from class attributes;
    content from `read()`:

        class AppVersion(MCPResource):
            '''Current deployed version.'''

            uri = "config://app/version"
            mime_type = "text/plain"

            def read(self) -> str:
                return settings.VERSION

    `read()` may return `str` (emitted as `text`) or `bytes` (emitted as
    base64 `blob`). Resource instances have `self.mcp` set by the
    dispatcher before `read()` is called — use it to read the caller's
    user, request, etc.

    Override `allowed_for(mcp)` (classmethod) to filter when the resource
    is included — same pattern as `MCPTool`.

    **URI templates.** For parametrized resources (one class, many URIs),
    set `uri_template` instead of `uri` and accept the template params on
    `__init__`:

        class Order(MCPResource):
            '''An order by ID.'''

            uri_template = "orders://{order_id}"
            mime_type = "application/json"

            def __init__(self, order_id: int):
                self.order_id = order_id

            def read(self) -> str:
                return str(Order.query.get(pk=self.order_id))

    Templates match RFC 6570 level 1 — `{name}` placeholders match a
    single path segment (no slashes). Extracted params are coerced to the
    `__init__` annotation when it's `int`, `float`, or `bool`; otherwise
    passed through as strings.
    """

    uri: str = ""
    uri_template: str = ""
    name: str = ""
    description: str = ""
    mime_type: str = ""

    _uri_pattern: re.Pattern[str] | None = None
    _init_hints: dict[str, Any] | None = None

    # Set by the MCPView dispatcher before `read()` is called.
    mcp: MCPView

    def __init__(self) -> None:
        """Default no-arg init — template resources override with typed params."""

    @abstractmethod
    def read(self) -> str | bytes:
        """Return the resource contents (str → text, bytes → base64 blob)."""

    @classmethod
    def allowed_for(cls, mcp: MCPView) -> bool:
        """Return False to exclude this resource from `mcp`'s resource set.

        Resources that return False are hidden from `resources/list`,
        `resources/templates/list`, and rejected from `resources/read` (as
        "unknown resource" — existence isn't leaked).
        """
        return True

    @classmethod
    def matches(cls, uri: str) -> dict[str, Any] | None:
        """If this resource can serve `uri`, return params for `__init__`.

        Returns `{}` for static URIs that match, `{param: value}` for
        template matches (values coerced via `__init__` annotations for
        `int`/`float`/`bool`; strings otherwise), or `None` if the URI
        doesn't match. Raises `ValueError` if the regex matches but
        coercion of the extracted params fails.
        """
        if cls.uri:
            return {} if uri == cls.uri else None
        if cls._uri_pattern is not None:
            match = cls._uri_pattern.fullmatch(uri)
            if match is None:
                return None
            return _coerce_template_params(cls, match.groupdict())
        return None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.__dict__.get("name"):
            cls.name = cls.__name__
        if not cls.__dict__.get("description"):
            doc = (cls.__doc__ or "").strip()
            if doc:
                cls.description = doc.splitlines()[0].strip()

        if cls.uri and cls.uri_template:
            raise TypeError(
                f"{cls.__name__} must set only one of `uri` or `uri_template`"
            )
        if cls.uri_template:
            cls._uri_pattern = _compile_uri_template(cls.uri_template)
            try:
                cls._init_hints = get_type_hints(cls.__init__)
            except (NameError, TypeError):
                # Unresolvable forward refs: skip coercion, pass raw strings.
                cls._init_hints = {}


_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def _compile_uri_template(template: str) -> re.Pattern[str]:
    """Compile an RFC 6570 level-1 URI template into a regex.

    Each `{name}` placeholder matches one path segment (no slashes).
    """
    pattern = ""
    last = 0
    for m in _PLACEHOLDER.finditer(template):
        pattern += re.escape(template[last : m.start()])
        pattern += f"(?P<{m.group(1)}>[^/]+)"
        last = m.end()
    pattern += re.escape(template[last:])
    return re.compile(pattern)


def _coerce_template_params(
    cls: type[MCPResource], raw: dict[str, str]
) -> dict[str, Any]:
    hints = cls._init_hints or {}
    coerced: dict[str, Any] = {}
    for name, value in raw.items():
        hint = hints.get(name)
        if hint is int:
            coerced[name] = int(value)
        elif hint is float:
            coerced[name] = float(value)
        elif hint is bool:
            coerced[name] = value.lower() in ("true", "1", "yes")
        else:
            coerced[name] = value
    return coerced
