from __future__ import annotations

import re
import string
from typing import Any

from plain.exceptions import ImproperlyConfigured
from plain.preflight import PreflightResult
from plain.utils.regex_helper import _lazy_re_compile

from .converters import _get_converter


class CheckURLMixin:
    # Expected to be set by subclasses
    regex: re.Pattern[str]
    name: str | None

    def describe(self) -> str:
        """
        Format the URL pattern for display in warning messages.
        """
        description = f"'{self}'"
        if self.name:
            description += f" [name='{self.name}']"
        return description


class RegexPattern(CheckURLMixin):
    """Internal regex pattern used by the resolver for root and namespace
    prefixes. Not exposed to user code — `path()` and `include()` accept
    only string routes."""

    name: str | None = None

    def __init__(self, regex: str):
        self.converters: dict[str, Any] = {}
        self.regex = re.compile(regex)

    def match(self, path: str) -> tuple[str, dict[str, Any]] | None:
        match = self.regex.search(path)
        if match:
            kwargs = match.groupdict()
            kwargs = {k: v for k, v in kwargs.items() if v is not None}
            return path[match.end() :], kwargs
        return None

    def preflight(self) -> list[PreflightResult]:
        return []

    def __str__(self) -> str:
        return self.regex.pattern


_PATH_PARAMETER_COMPONENT_RE = _lazy_re_compile(
    r"<(?:(?P<converter>[^>:]+):)?(?P<parameter>[^>]+)>"
)


def _route_to_regex(
    route: str, is_endpoint: bool = False
) -> tuple[str, dict[str, Any]]:
    """
    Convert a path pattern into a regular expression. Return the regular
    expression and a dictionary mapping the capture names to the converters.
    For example, 'foo/<int:id>' returns '^foo\\/(?P<id>[0-9]+)'
    and {'id': <plain.urls.converters.IntConverter>}.
    """
    original_route = route
    parts = ["^"]
    converters = {}
    while True:
        match = _PATH_PARAMETER_COMPONENT_RE.search(route)
        if not match:
            parts.append(re.escape(route))
            break
        elif not set(match.group()).isdisjoint(string.whitespace):
            raise ImproperlyConfigured(
                f"URL route '{original_route}' cannot contain whitespace in angle brackets "
                "<…>."
            )
        parts.append(re.escape(route[: match.start()]))
        route = route[match.end() :]
        parameter = match["parameter"]
        if not parameter.isidentifier():
            raise ImproperlyConfigured(
                f"URL route '{original_route}' uses parameter name {parameter!r} which isn't a valid "
                "Python identifier."
            )
        raw_converter = match["converter"]
        if raw_converter is None:
            # If a converter isn't specified, the default is `str`.
            raw_converter = "str"
        try:
            converter = _get_converter(raw_converter)
        except KeyError as e:
            raise ImproperlyConfigured(
                f"URL route {original_route!r} uses invalid converter {raw_converter!r}."
            ) from e
        converters[parameter] = converter
        parts.append("(?P<" + parameter + ">" + converter.regex + ")")
    if is_endpoint:
        parts.append(r"\Z")
    return "".join(parts), converters


class RoutePattern(CheckURLMixin):
    def __init__(self, route: str, name: str | None = None, is_endpoint: bool = False):
        self._route = route
        self._is_endpoint = is_endpoint
        self.name = name
        self.converters = _route_to_regex(str(route), is_endpoint)[1]
        self.regex = self._compile(str(route))

    def match(self, path: str) -> tuple[str, dict[str, Any]] | None:
        match = self.regex.search(path)
        if match:
            kwargs = match.groupdict()
            for key, value in kwargs.items():
                converter = self.converters[key]
                try:
                    kwargs[key] = converter.to_python(value)
                except ValueError:
                    return None
            return path[match.end() :], kwargs
        return None

    def preflight(self) -> list[PreflightResult]:
        warnings: list[PreflightResult] = []
        route = self._route
        if "(?P<" in route or route.startswith("^") or route.endswith("$"):
            warnings.append(
                PreflightResult(
                    fix=f"Your URL pattern {self.describe()} has a route that contains '(?P<', begins "
                    "with a '^', or ends with a '$'. This was likely an oversight "
                    "when migrating to plain.urls.path().",
                    warning=True,
                    id="urls.path_migration_warning",
                )
            )
        return warnings

    def _compile(self, route: str) -> re.Pattern[str]:
        return re.compile(_route_to_regex(route, self._is_endpoint)[0])

    def __str__(self) -> str:
        return str(self._route)


class URLPattern:
    def __init__(
        self,
        *,
        pattern: RoutePattern,
        view_class: type,
    ):
        self.pattern = pattern
        self.view_class = view_class

    @property
    def name(self) -> str | None:
        return self.pattern.name

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.pattern.describe()}>"

    def preflight(self) -> list[PreflightResult]:
        warnings = self._check_pattern_name()
        warnings.extend(self.pattern.preflight())
        return warnings

    def _check_pattern_name(self) -> list[PreflightResult]:
        """
        Check that the pattern name does not contain a colon.
        """
        if self.pattern.name is not None and ":" in self.pattern.name:
            warning = PreflightResult(
                fix=f"Your URL pattern {self.pattern.describe()} has a name including a ':'. Remove the colon, to "
                "avoid ambiguous namespace references.",
                warning=True,
                id="urls.pattern_name_contains_colon",
            )
            return [warning]
        else:
            return []

    def resolve(self, path: str) -> Any:
        match = self.pattern.match(path)
        if match:
            new_path, captured_kwargs = match
            from .resolvers import ResolverMatch

            return ResolverMatch(
                view_class=self.view_class,
                kwargs=captured_kwargs,
                url_name=self.pattern.name,
                route=str(self.pattern),
            )
        return None
