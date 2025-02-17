import functools
import inspect
import re
import string

from plain.exceptions import ImproperlyConfigured
from plain.preflight import Error, Warning
from plain.runtime import settings
from plain.utils.functional import cached_property
from plain.utils.regex_helper import _lazy_re_compile

from .converters import get_converter


class CheckURLMixin:
    def describe(self):
        """
        Format the URL pattern for display in warning messages.
        """
        description = f"'{self}'"
        if self.name:
            description += f" [name='{self.name}']"
        return description

    def _check_pattern_startswith_slash(self):
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
            warning = Warning(
                f"Your URL pattern {self.describe()} has a route beginning with a '/'. Remove this "
                "slash as it is unnecessary. If this pattern is targeted in an "
                "include(), ensure the include() pattern has a trailing '/'.",
                id="urls.W002",
            )
            return [warning]
        else:
            return []


class RegexPattern(CheckURLMixin):
    def __init__(self, regex, name=None, is_endpoint=False):
        self._regex = regex
        self._regex_dict = {}
        self._is_endpoint = is_endpoint
        self.name = name
        self.converters = {}
        self.regex = self._compile(str(regex))

    def match(self, path):
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

    def check(self):
        warnings = []
        warnings.extend(self._check_pattern_startswith_slash())
        if not self._is_endpoint:
            warnings.extend(self._check_include_trailing_dollar())
        return warnings

    def _check_include_trailing_dollar(self):
        regex_pattern = self.regex.pattern
        if regex_pattern.endswith("$") and not regex_pattern.endswith(r"\$"):
            return [
                Warning(
                    f"Your URL pattern {self.describe()} uses include with a route ending with a '$'. "
                    "Remove the dollar from the route to avoid problems including "
                    "URLs.",
                    id="urls.W001",
                )
            ]
        else:
            return []

    def _compile(self, regex):
        """Compile and return the given regular expression."""
        try:
            return re.compile(regex)
        except re.error as e:
            raise ImproperlyConfigured(
                f'"{regex}" is not a valid regular expression: {e}'
            ) from e

    def __str__(self):
        return str(self._regex)


_PATH_PARAMETER_COMPONENT_RE = _lazy_re_compile(
    r"<(?:(?P<converter>[^>:]+):)?(?P<parameter>[^>]+)>"
)


def _route_to_regex(route, is_endpoint=False):
    """
    Convert a path pattern into a regular expression. Return the regular
    expression and a dictionary mapping the capture names to the converters.
    For example, 'foo/<int:pk>' returns '^foo\\/(?P<pk>[0-9]+)'
    and {'pk': <plain.urls.converters.IntConverter>}.
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
            converter = get_converter(raw_converter)
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
    def __init__(self, route, name=None, is_endpoint=False):
        self._route = route
        self._regex_dict = {}
        self._is_endpoint = is_endpoint
        self.name = name
        self.converters = _route_to_regex(str(route), is_endpoint)[1]
        self.regex = self._compile(str(route))

    def match(self, path):
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

    def check(self):
        warnings = self._check_pattern_startswith_slash()
        route = self._route
        if "(?P<" in route or route.startswith("^") or route.endswith("$"):
            warnings.append(
                Warning(
                    f"Your URL pattern {self.describe()} has a route that contains '(?P<', begins "
                    "with a '^', or ends with a '$'. This was likely an oversight "
                    "when migrating to plain.urls.path().",
                    id="2_0.W001",
                )
            )
        return warnings

    def _compile(self, route):
        return re.compile(_route_to_regex(route, self._is_endpoint)[0])

    def __str__(self):
        return str(self._route)


class URLPattern:
    def __init__(self, *, pattern, view, name=None):
        self.pattern = pattern
        self.view = view
        self.name = name

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.pattern.describe()}>"

    def check(self):
        warnings = self._check_pattern_name()
        warnings.extend(self.pattern.check())
        return warnings

    def _check_pattern_name(self):
        """
        Check that the pattern name does not contain a colon.
        """
        if self.pattern.name is not None and ":" in self.pattern.name:
            warning = Warning(
                f"Your URL pattern {self.pattern.describe()} has a name including a ':'. Remove the colon, to "
                "avoid ambiguous namespace references.",
                id="urls.W003",
            )
            return [warning]
        else:
            return []

    def _check_view(self):
        from plain.views import View

        view = self.view
        if inspect.isclass(view) and issubclass(view, View):
            return [
                Error(
                    f"Your URL pattern {self.pattern.describe()} has an invalid view, pass {view.__name__}.as_view() "
                    f"instead of {view.__name__}.",
                    id="urls.E009",
                )
            ]
        return []

    def resolve(self, path):
        match = self.pattern.match(path)
        if match:
            new_path, args, captured_kwargs = match
            from .resolvers import ResolverMatch

            return ResolverMatch(
                self.view,
                args,
                captured_kwargs,
                self.pattern.name,
                route=str(self.pattern),
                captured_kwargs=captured_kwargs,
            )

    @cached_property
    def lookup_str(self):
        """
        A string that identifies the view (e.g. 'path.to.view_function' or
        'path.to.ClassBasedView').
        """
        view = self.view
        if isinstance(view, functools.partial):
            view = view.func
        if hasattr(view, "view_class"):
            view = view.view_class
        elif not hasattr(view, "__name__"):
            return view.__module__ + "." + view.__class__.__name__
        return view.__module__ + "." + view.__qualname__
