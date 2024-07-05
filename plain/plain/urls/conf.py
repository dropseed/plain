"""Functions for use in URLsconfs."""
from functools import partial

from plain.exceptions import ImproperlyConfigured

from .resolvers import (
    RegexPattern,
    RoutePattern,
    URLPattern,
    URLResolver,
)


def include(arg, namespace=None):
    default_namespace = None
    if isinstance(arg, tuple):
        # Callable returning a namespace hint.
        try:
            urlconf_module, default_namespace = arg
        except ValueError:
            if namespace:
                raise ImproperlyConfigured(
                    "Cannot override the namespace for a dynamic module that "
                    "provides a namespace."
                )
            raise ImproperlyConfigured(
                "Passing a %d-tuple to include() is not supported. Pass a "
                "2-tuple containing the list of patterns and default_namespace, and "
                "provide the namespace argument to include() instead." % len(arg)
            )
    else:
        # No namespace hint - use manually provided namespace.
        urlconf_module = arg

    patterns = getattr(urlconf_module, "urlpatterns", urlconf_module)
    default_namespace = getattr(urlconf_module, "default_namespace", default_namespace)
    if namespace and not default_namespace:
        raise ImproperlyConfigured(
            "Specifying a namespace in include() without providing an default_namespace "
            "is not supported. Set the default_namespace attribute in the included "
            "module, or pass a 2-tuple containing the list of patterns and "
            "default_namespace instead.",
        )
    namespace = namespace or default_namespace
    # Make sure the patterns can be iterated through (without this, some
    # testcases will break).
    if isinstance(patterns, list | tuple):
        for url_pattern in patterns:
            getattr(url_pattern, "pattern", None)
    return (urlconf_module, default_namespace, namespace)


def _path(route, view, kwargs=None, name=None, Pattern=None):
    from plain.views import View

    if kwargs is not None and not isinstance(kwargs, dict):
        raise TypeError(
            f"kwargs argument must be a dict, but got {kwargs.__class__.__name__}."
        )

    if isinstance(view, list | tuple):
        # For include(...) processing.
        pattern = Pattern(route, is_endpoint=False)
        urlconf_module, default_namespace, namespace = view
        return URLResolver(
            pattern,
            urlconf_module,
            kwargs,
            default_namespace=default_namespace,
            namespace=namespace,
        )

    if isinstance(view, View):
        view_cls_name = view.__class__.__name__
        raise TypeError(
            f"view must be a callable, pass {view_cls_name} or {view_cls_name}.as_view(*args, **kwargs), not "
            f"{view_cls_name}()."
        )

    # Automatically call view.as_view() for class-based views
    if as_view := getattr(view, "as_view", None):
        pattern = Pattern(route, name=name, is_endpoint=True)
        return URLPattern(pattern, as_view(), kwargs, name)

    # Function-based views or view_class.as_view() usage
    if callable(view):
        pattern = Pattern(route, name=name, is_endpoint=True)
        return URLPattern(pattern, view, kwargs, name)

    raise TypeError("view must be a callable or a list/tuple in the case of include().")


path = partial(_path, Pattern=RoutePattern)
re_path = partial(_path, Pattern=RegexPattern)
