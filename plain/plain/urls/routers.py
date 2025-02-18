import re
from abc import ABC
from types import ModuleType
from typing import TYPE_CHECKING

from plain.exceptions import ImproperlyConfigured

from .patterns import RegexPattern, RoutePattern, URLPattern
from .resolvers import (
    URLResolver,
)

if TYPE_CHECKING:
    from plain.views import View


class RouterBase(ABC):
    namespace: str = ""
    urls: list  # Required


class RoutersRegistry:
    """Keep track of all the Routers that are explicitly registered in packages."""

    def __init__(self):
        self._routers = {}

    def register_router(self, router_class):
        router_module_name = router_class.__module__
        self._routers[router_module_name] = router_class
        return router_class

    def get_module_router(self, module):
        if isinstance(module, str):
            module_name = module
        else:
            module_name = module.__name__

        try:
            return self._routers[module_name]
        except KeyError as e:
            registered_routers = ", ".join(self._routers.keys()) or "None"
            raise ImproperlyConfigured(
                f"Router {module_name} is not registered with the resolver. Use @register_router on the Router class in urls.py.\n\nRegistered routers: {registered_routers}"
            ) from e


def include(
    route: str | re.Pattern, module_or_urls: list | tuple | str | ModuleType
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

    if isinstance(module_or_urls, list | tuple):
        # We were given an explicit list of sub-patterns,
        # so we generate a router for it
        class _IncludeRouter(RouterBase):
            urls = module_or_urls

        return URLResolver(pattern=pattern, router_class=_IncludeRouter)
    else:
        # We were given a module, so we need to look up the router for that module
        module = module_or_urls
        router_class = routers_registry.get_module_router(module)

        return URLResolver(
            pattern=pattern,
            router_class=router_class,
        )


def path(route: str | re.Pattern, view: "View", *, name: str = "") -> URLPattern:
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
    if issubclass(view, View):
        return URLPattern(pattern=pattern, view=view.as_view(), name=name)

    # If you called View.as_view() yourself (or technically any callable)
    if callable(view):
        return URLPattern(pattern=pattern, view=view, name=name)

    raise TypeError("view must be a View class or View.as_view()")


routers_registry = RoutersRegistry()
register_router = routers_registry.register_router
