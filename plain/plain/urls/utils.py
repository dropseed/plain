from plain.utils.functional import lazy

from .exceptions import NoReverseMatch
from .resolvers import get_ns_resolver, get_resolver


def reverse(viewname, *args, **kwargs):
    resolver = get_resolver()

    if not isinstance(viewname, str):
        view = viewname
    else:
        *path, view = viewname.split(":")

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
                    raise NoReverseMatch(f"{key} is not a registered namespace")
        if ns_pattern:
            resolver = get_ns_resolver(
                ns_pattern, resolver, tuple(ns_converters.items())
            )

    return resolver.reverse(view, *args, **kwargs)


reverse_lazy = lazy(reverse, str)
