from __future__ import annotations

import re
import string
from typing import Any

from plain.exceptions import ImproperlyConfigured
from plain.internal import internalcode
from plain.preflight import PreflightResult
from plain.runtime import settings
from plain.utils.regex_helper import _lazy_re_compile

from .converters import _get_converter


@internalcode
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

    def _check_pattern_startswith_slash(self) -> list[PreflightResult]:
        """
        Check that the pattern does not begin with a forward slash.
        """
        regex_pattern = self.regex.pattern
        if not settings.APPEND_SLASH:
            # Skip check as it can be useful to start a URL pattern with a slash
            # when APPEND_SLASH=False.
            return []
        if regex_pattern.startswith(("/", "^/", "^\\/")) and not regex_pattern.endswith(
            "/"
        ):
            warning = PreflightResult(
                fix=f"URL pattern {self.describe()} starts with unnecessary '/'. Remove the leading slash.",
                warning=True,
                id="urls.pattern_starts_with_slash",
            )
            return [warning]
        else:
            return []


class RegexPattern(CheckURLMixin):
    def __init__(self, regex: str, name: str | None = None, is_endpoint: bool = False):
        self._regex = regex
        self._is_endpoint = is_endpoint
        self.name = name
        self.converters: dict[str, Any] = {}
        self.regex = self._compile(str(regex))

    def match(self, path: str) -> tuple[str, tuple[Any, ...], dict[str, Any]] | None:
        match = (
            self.regex.fullmatch(path)
            if self._is_endpoint and self.regex.pattern.endswith("$")
            else self.regex.search(path)
        )
        if match:
            # If there are any named groups, use those as kwargs, ignoring
            # non-named groups. Otherwise, pass all non-named arguments as
            # positional arguments.
            kwargs = match.groupdict()
            args = () if kwargs else match.groups()
            kwargs = {k: v for k, v in kwargs.items() if v is not None}
            return path[match.end() :], args, kwargs
        return None

    def preflight(self) -> list[PreflightResult]:
        warnings = []
        warnings.extend(self._check_pattern_startswith_slash())
        if not self._is_endpoint:
            warnings.extend(self._check_include_trailing_dollar())
        return warnings

    def _check_include_trailing_dollar(self) -> list[PreflightResult]:
        regex_pattern = self.regex.pattern
        if regex_pattern.endswith("$") and not regex_pattern.endswith(r"\$"):
            return [
                PreflightResult(
                    fix=f"Include pattern {self.describe()} ends with '$' which prevents URL inclusion. Remove the dollar sign.",
                    warning=True,
                    id="urls.include_pattern_ends_with_dollar",
                )
            ]
        else:
            return []

    def _compile(self, regex: str) -> re.Pattern[str]:
        """Compile and return the given regular expression."""
        try:
            return re.compile(regex)
        except re.error as e:
            raise ImproperlyConfigured(
                f'"{regex}" is not a valid regular expression: {e}'
            ) from e

    def __str__(self) -> str:
        return str(self._regex)


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

    def match(self, path: str) -> tuple[str, tuple[()], dict[str, Any]] | None:
        match = self.regex.search(path)
        if match:
            # RoutePattern doesn't allow non-named groups so args are ignored.
            kwargs = match.groupdict()
            for key, value in kwargs.items():
                converter = self.converters[key]
                try:
                    kwargs[key] = converter.to_python(value)
                except ValueError:
                    return None
            return path[match.end() :], (), kwargs
        return None

    def preflight(self) -> list[PreflightResult]:
        warnings = self._check_pattern_startswith_slash()
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
        pattern: RegexPattern | RoutePattern,
        view: Any,
        name: str | None = None,
    ):
        self.pattern = pattern
        self.view = view
        self.name = name

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
            new_path, args, captured_kwargs = match
            from .resolvers import ResolverMatch

            return ResolverMatch(
                view=self.view,
                args=args,
                kwargs=captured_kwargs,
                url_name=self.pattern.name,
                route=str(self.pattern),
            )
        return None
