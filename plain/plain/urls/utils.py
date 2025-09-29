from __future__ import annotations

from typing import Any

from plain.utils.functional import lazy

from .exceptions import NoReverseMatch
from .resolvers import get_ns_resolver, get_resolver


def reverse(url_name: str, *args: Any, **kwargs: Any) -> str:
    resolver = get_resolver()

    *path, view = url_name.split(":")

    current_path = None

    resolved_path = []
    ns_pattern = ""
    ns_converters = {}
    for ns in path:
        current_ns = current_path.pop() if current_path else None

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
        resolver = get_ns_resolver(ns_pattern, resolver, tuple(ns_converters.items()))

    return resolver.reverse(view, *args, **kwargs)


reverse_lazy = lazy(reverse, str)
