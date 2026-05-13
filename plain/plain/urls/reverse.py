from __future__ import annotations

from typing import Any

from plain.runtime import settings
from plain.utils.functional import lazy

from .exceptions import NoReverseMatch
from .resolvers import get_resolver
from .segments import Segment


def reverse(url_name: str, **kwargs: Any) -> str:
    resolver = get_resolver()

    *path, view = url_name.split(":")

    resolved_path: list[str] = []
    prefix_segments: tuple[Segment, ...] = ()
    for ns in path:
        try:
            extra_segments, resolver = resolver.namespace_dict[ns]
            resolved_path.append(ns)
            prefix_segments = prefix_segments + extra_segments
        except KeyError:
            if resolved_path:
                raise NoReverseMatch(
                    f"'{ns}' is not a registered namespace inside "
                    f"'{':'.join(resolved_path)}'"
                )
            raise NoReverseMatch(f"'{ns}' is not a registered namespace")

    # `prefix_segments` is positional-only on `URLResolver.reverse`
    # specifically to avoid colliding with user-route kwargs of the same
    # name — don't switch this call to keyword form.
    return resolver.reverse(view, prefix_segments, **kwargs)


reverse_lazy = lazy(reverse, str)


def absolute_url(path: str) -> str:
    """Convert a relative path to an absolute URL using the BASE_URL setting."""
    if not settings.BASE_URL:
        raise ValueError(
            "The BASE_URL setting must be configured to generate absolute URLs."
        )

    base = settings.BASE_URL.rstrip("/")
    if path and not path.startswith("/"):
        path = "/" + path

    return base + path


def reverse_absolute(url_name: str, **kwargs: Any) -> str:
    """Reverse a URL name and return an absolute URL using the BASE_URL setting."""
    return absolute_url(reverse(url_name, **kwargs))
