import re

from .patterns import RegexPattern, RoutePattern, URLPattern
from .resolvers import (
    URLResolver,
)


class Router:
    """
    Base class for defining url patterns.

    A namespace is required, and generally recommended,
    except for the root router in app.urls where it is typically "".
    """

    namespace: str
    urls: list


def include(
    route: str | re.Pattern, router_or_urls: list | tuple | str | type[Router]
) -> URLResolver:
    """
    Include URLs from another module or a nested list of URL patterns.
    """
    if isinstance(route, str):
        pattern = RoutePattern(route, is_endpoint=False)
    elif isinstance(route, re.Pattern):
        pattern = RegexPattern(route.pattern, is_endpoint=False)
    else:
        raise TypeError("include() route must be a string or regex")

    if isinstance(router_or_urls, list | tuple):
        # We were given an explicit list of sub-patterns,
        # so we generate a router for it
        class _IncludeRouter(Router):
            namespace = ""
            urls = router_or_urls

        return URLResolver(pattern=pattern, router=_IncludeRouter())
    elif isinstance(router_or_urls, type) and issubclass(router_or_urls, Router):
        router_class = router_or_urls
        router = router_class()

        return URLResolver(
            pattern=pattern,
            router=router,
        )
    else:
        raise TypeError(
            f"include() urls must be a list, tuple, or Router class (not a Router() instance): {router_or_urls}"
        )


def path(route: str | re.Pattern, view_class: type, *, name: str = "") -> URLPattern:
    """
    Map a URL pattern to a view class.
    """
    if isinstance(route, str):
        pattern = RoutePattern(route, name=name, is_endpoint=True)
    elif isinstance(route, re.Pattern):
        pattern = RegexPattern(route.pattern, name=name, is_endpoint=True)
    else:
        raise TypeError("path() route must be a string or regex")

    if not isinstance(view_class, type):
        raise TypeError(
            f"path() requires a class, not an instance or callable: {view_class!r}"
        )

    return URLPattern(pattern=pattern, view_class=view_class, name=name)
