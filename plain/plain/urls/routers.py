from abc import ABC

from plain.exceptions import ImproperlyConfigured

from .patterns import RoutePattern, URLPattern
from .resolvers import (
    URLResolver,
)


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


def include(route, module_or_urls, *, Pattern=RoutePattern):
    pattern = Pattern(route, is_endpoint=False)

    if isinstance(module_or_urls, list | tuple):
        # We were given an explicit list of sub-patterns,
        # so we generate a router for it
        class _IncludeRouter(RouterBase):
            urls = module_or_urls

        return URLResolver(pattern=pattern, router_class=_IncludeRouter, namespace=None)
    else:
        # We were given a module, so we need to look up the router for that module
        module = module_or_urls
        router = routers.get_module_router(module)
        namespace = router.namespace

        return URLResolver(
            pattern=pattern,
            router_class=router,
            namespace=namespace,
        )


def path(route, view, *, name=None, Pattern=RoutePattern):
    from plain.views import View

    pattern = Pattern(route, name=name, is_endpoint=True)

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


routers = RoutersRegistry()
register_router = routers.register_router
