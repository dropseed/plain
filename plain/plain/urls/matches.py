from __future__ import annotations

from typing import Any


class ResolverMatch:
    def __init__(
        self,
        *,
        view_class: type,
        kwargs: dict[str, Any],
        url_name: str | None = None,
        namespaces: list[str] | None = None,
        route: str | None = None,
    ):
        self.view_class = view_class
        self.kwargs = kwargs
        self.url_name = url_name
        self.route = route

        self.namespaces = [x for x in namespaces if x] if namespaces else []
        self.namespace = ":".join(self.namespaces)

        self.namespaced_url_name = (
            ":".join(self.namespaces + [url_name]) if url_name else None
        )
