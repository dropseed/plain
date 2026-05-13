from __future__ import annotations

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


def _strip_slashes(route: str) -> str:
    """Strip both leading and trailing slashes.

    Slashes on the route string carry no per-route signal in the new
    model — the canonical trailing slash comes from
    `URLS_TRAILING_SLASH` and (for `path()`) the `force_trailing_slash`
    override. Strings like `"admin/"` and `"admin"` produce identical
    routes; the leading slash is also stripped (no scheme-relative URL
    hazard).
    """
    return route.strip("/")


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

    raw_route = _strip_slashes(route)
    segments = _route_to_segments(raw_route)

    if isinstance(router_or_urls, list | tuple):

        class _IncludeRouter(Router):
            namespace = ""
            urls = list(router_or_urls)

        return URLResolver(
            segments=segments, raw_route=raw_route, router=_IncludeRouter()
        )
    elif isinstance(router_or_urls, type) and issubclass(router_or_urls, Router):
        return URLResolver(
            segments=segments, raw_route=raw_route, router=router_or_urls()
        )
    else:
        raise TypeError(
            f"include() urls must be a list, tuple, or Router class (not a Router() instance): {router_or_urls}"
        )


def path(
    route: str,
    view_class: type,
    *,
    name: str = "",
    force_trailing_slash: bool | None = None,
) -> URLPattern:
    """Map a URL pattern to a view class.

    `force_trailing_slash` overrides the app-wide
    `URLS_TRAILING_SLASH` setting for this endpoint:

    - `None` (default) — follow the global setting
    - `True` — endpoint always has a trailing slash
    - `False` — endpoint never has a trailing slash
    """
    if not isinstance(route, str):
        raise TypeError(f"path() route must be a string, not {type(route).__name__}")

    if not isinstance(view_class, type):
        raise TypeError(
            f"path() requires a class, not an instance or callable: {view_class!r}"
        )

    raw_route = _strip_slashes(route)
    return URLPattern(
        segments=_route_to_segments(raw_route),
        raw_route=raw_route,
        name=name,
        view_class=view_class,
        force_trailing_slash=force_trailing_slash,
    )
