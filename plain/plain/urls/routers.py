from .patterns import URLPattern
from .resolvers import URLResolver
from .segments import _route_to_segments


class Router:
    """
    Base class for defining url patterns.

    A namespace is required, and generally recommended,
    except for the root router in app.urls where it is typically "".

    `urls` is read once at `URLResolver.__init__` time, when the reverse
    and namespace lookup tables are built. Mutating `urls` afterward will
    not refresh those tables — treat the list as immutable once the app
    is running.
    """

    namespace: str
    urls: list[URLPattern | URLResolver]


def _normalize_include_route(route: str) -> str:
    """Strip leading/trailing slashes; append a trailing slash if non-empty.

    `include("admin")`, `include("admin/")`, and `include("/admin/")` all
    collapse to `"admin/"`. The empty string stays empty (root include).
    """
    stripped = route.strip("/")
    if not stripped:
        return ""
    return f"{stripped}/"


def include(
    route: str,
    router_or_urls: (
        list[URLPattern | URLResolver]
        | tuple[URLPattern | URLResolver, ...]
        | type[Router]
    ),
) -> URLResolver:
    """
    Include URLs from another module or a nested list of URL patterns.
    """
    if not isinstance(route, str):
        raise TypeError(f"include() route must be a string, not {type(route).__name__}")

    raw_route = _normalize_include_route(route)
    parsed = _route_to_segments(raw_route)

    if isinstance(router_or_urls, list | tuple):

        class _IncludeRouter(Router):
            namespace = ""
            urls = list(router_or_urls)

        return URLResolver(route=parsed, raw_route=raw_route, router=_IncludeRouter())
    elif isinstance(router_or_urls, type) and issubclass(router_or_urls, Router):
        return URLResolver(route=parsed, raw_route=raw_route, router=router_or_urls())
    else:
        raise TypeError(
            f"include() urls must be a list, tuple, or Router class (not a Router() instance): {router_or_urls}"
        )


def path(route: str, view_class: type, *, name: str = "") -> URLPattern:
    """
    Map a URL pattern to a view class.
    """
    if not isinstance(route, str):
        raise TypeError(f"path() route must be a string, not {type(route).__name__}")

    if not isinstance(view_class, type):
        raise TypeError(
            f"path() requires a class, not an instance or callable: {view_class!r}"
        )

    # Strip leading slashes; trailing slash is part of the route's
    # canonical form (defining `path("users/")` vs `path("users")`
    # determines the URL the framework redirects to).
    raw_route = route.lstrip("/")
    return URLPattern(
        route=_route_to_segments(raw_route),
        raw_route=raw_route,
        name=name,
        view_class=view_class,
    )
