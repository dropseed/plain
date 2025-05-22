import re
from typing import TYPE_CHECKING

from .patterns import RegexPattern, RoutePattern, URLPattern
from .resolvers import (
    URLResolver,
)

if TYPE_CHECKING:
    from plain.views import View


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


def path(route: str | re.Pattern, view: type["View"], *, name: str = "") -> URLPattern:
    """
    Standard URL with a view.
    """
    from plain.views import View

    if isinstance(route, str):
        pattern = RoutePattern(route, name=name, is_endpoint=True)
    elif isinstance(route, re.Pattern):
        pattern = RegexPattern(route.pattern, name=name, is_endpoint=True)
    else:
        raise TypeError("path() route must be a string or regex")

    # You can't pass a View() instance to path()
    if isinstance(view, View):
        view_cls_name = view.__class__.__name__
        raise TypeError(
            f"view must be a callable, pass {view_cls_name} or {view_cls_name}.as_view(*args, **kwargs), not "
            f"{view_cls_name}()."
        )

    # You typically pass a View class and we call as_view() for you
    if isinstance(view, type) and issubclass(view, View):
        return URLPattern(pattern=pattern, view=view.as_view(), name=name)

    # If you called View.as_view() yourself (or technically any callable)
    if callable(view):
        return URLPattern(pattern=pattern, view=view, name=name)

    raise TypeError("view must be a View class or View.as_view()")
