from .patterns import RoutePattern, URLPattern
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


def _normalize_include_route(route: str) -> str:
    """Strip leading/trailing slashes; append a trailing slash if non-empty.

    `include("admin")`, `include("admin/")`, and `include("/admin/")` all
    collapse to `"admin/"`. The empty string stays empty (root include).

    Routes that still look like regex residue after stripping (`^`, `$`,
    `(?P<`) skip the trailing-slash append, so `RoutePattern.preflight()`
    can still surface `urls.path_migration_warning`.
    """
    stripped = route.strip("/")
    if not stripped:
        return ""
    if "(?P<" in stripped or stripped.startswith("^") or stripped.endswith("$"):
        return stripped
    return f"{stripped}/"


def include(route: str, router_or_urls: list | tuple | type[Router]) -> URLResolver:
    """
    Include URLs from another module or a nested list of URL patterns.
    """
    if not isinstance(route, str):
        raise TypeError(f"include() route must be a string, not {type(route).__name__}")

    pattern = RoutePattern(_normalize_include_route(route), is_endpoint=False)

    if isinstance(router_or_urls, list | tuple):

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
    pattern = RoutePattern(route.lstrip("/"), name=name, is_endpoint=True)
    return URLPattern(pattern=pattern, view_class=view_class)
