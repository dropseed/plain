from threading import local

from plain.utils.functional import lazy

from .exceptions import NoReverseMatch, Resolver404
from .resolvers import _get_cached_resolver, get_ns_resolver, get_resolver

# Overridden URLconfs for each thread are stored here.
_urlconfs = local()


def resolve(path, urlconf=None):
    if urlconf is None:
        urlconf = get_urlconf()
    return get_resolver(urlconf).resolve(path)


def reverse(viewname, urlconf=None, args=None, kwargs=None, using_namespace=None):
    if urlconf is None:
        urlconf = get_urlconf()
    resolver = get_resolver(urlconf)
    args = args or []
    kwargs = kwargs or {}

    if not isinstance(viewname, str):
        view = viewname
    else:
        *path, view = viewname.split(":")

        if using_namespace:
            current_path = using_namespace.split(":")
            current_path.reverse()
        else:
            current_path = None

        resolved_path = []
        ns_pattern = ""
        ns_converters = {}
        for ns in path:
            current_ns = current_path.pop() if current_path else None
            # Lookup the name to see if it could be an app identifier.
            try:
                app_list = resolver.app_dict[ns]
                # Yes! Path part matches an app in the current Resolver.
                if current_ns and current_ns in app_list:
                    # If we are reversing for a particular app, use that
                    # namespace.
                    ns = current_ns
                elif ns not in app_list:
                    # The name isn't shared by one of the instances (i.e.,
                    # the default) so pick the first instance as the default.
                    ns = app_list[0]
            except KeyError:
                pass

            if ns != current_ns:
                current_path = None

            try:
                extra, resolver = resolver.namespace_dict[ns]
                resolved_path.append(ns)
                ns_pattern += extra
                ns_converters.update(resolver.pattern.converters)
            except KeyError as key:
                if resolved_path:
                    raise NoReverseMatch(
                        "{} is not a registered namespace inside '{}'".format(
                            key, ":".join(resolved_path)
                        )
                    )
                else:
                    raise NoReverseMatch("%s is not a registered namespace" % key)
        if ns_pattern:
            resolver = get_ns_resolver(
                ns_pattern, resolver, tuple(ns_converters.items())
            )

    return resolver.reverse(view, *args, **kwargs)


reverse_lazy = lazy(reverse, str)


def clear_url_caches():
    _get_cached_resolver.cache_clear()
    get_ns_resolver.cache_clear()


def set_urlconf(urlconf_name):
    """
    Set the URLconf for the current thread (overriding the default one in
    settings). If urlconf_name is None, revert back to the default.
    """
    if urlconf_name:
        _urlconfs.value = urlconf_name
    else:
        if hasattr(_urlconfs, "value"):
            del _urlconfs.value


def get_urlconf(default=None):
    """
    Return the root URLconf to use for the current thread if it has been
    changed from the default one.
    """
    return getattr(_urlconfs, "value", default)


def is_valid_path(path, urlconf=None):
    """
    Return the ResolverMatch if the given path resolves against the default URL
    resolver, False otherwise. This is a convenience method to make working
    with "is this a match?" cases easier, avoiding try...except blocks.
    """
    try:
        return resolve(path, urlconf)
    except Resolver404:
        return False
