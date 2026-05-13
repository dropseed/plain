"""URL routing exceptions.

Public (raised by the framework, catchable by user code):
- `Resolver404` — no route matched the request path.
- `NoReverseMatch` — `reverse()` couldn't build a URL for the given name.

Internal (framework-internal signals; the handler catches them and
converts them to HTTP responses — not intended for user code):
- `Resolver308` — request matched but at a non-canonical URL; redirect.
- `Resolver400` — request path was malformed (e.g. `..` below root).
"""

from __future__ import annotations

from plain.http import BadRequestError400, NotFoundError404


class Resolver404(NotFoundError404):
    pass


class Resolver308(Exception):
    """Resolver matched but the request must redirect to a canonical URL.

    Raised for trailing-slash mismatches against an existing route, for
    `//`-collapse normalization, and for `.`/`..` segment resolution.
    The canonical attribute carries the full path (with leading `/` and
    any query string omitted) to redirect to.
    """

    def __init__(self, canonical: str):
        super().__init__(f"Redirect to {canonical!r}")
        self.canonical = canonical


class Resolver400(BadRequestError400):
    """Resolver rejected the request path as malformed.

    Today the only trigger is `..` segments that would resolve below the
    URL root — there's no legitimate request that does that.
    """


class NoReverseMatch(Exception):
    pass
