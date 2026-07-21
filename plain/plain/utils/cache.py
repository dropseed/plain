"""
This module contains helper functions for controlling caching. It does so by
managing the "Vary" header of responses. It includes functions to patch the
header of response objects directly and decorators that change functions to do
that header-patching themselves.

For information on the Vary header, see RFC 9110 Section 12.5.5.

Essentially, the "Vary" HTTP header defines which headers a cache should take
into account when building its cache key. Requests with the same path but
different header content for headers named in "Vary" need to get different
cache keys to prevent delivery of wrong content.

An example: i18n middleware would need to distinguish caches by the
"Accept-language" header.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from .http import http_date
from .regex_helper import _lazy_re_compile

if TYPE_CHECKING:
    from plain.http import Response

_cc_delim_re = _lazy_re_compile(r"\s*,\s*")


def patch_response_headers(response: Response, cache_timeout: int | float) -> None:
    """
    Add HTTP caching headers to the given HttpResponse: Expires and
    Cache-Control.

    Each header is only added if it isn't already set.
    """
    if cache_timeout < 0:
        cache_timeout = 0  # Can't have max-age negative
    if "Expires" not in response.headers:
        response.headers["Expires"] = http_date(time.time() + cache_timeout)
    patch_cache_control(response, max_age=int(cache_timeout))


def add_never_cache_headers(response: Response) -> None:
    """
    Add headers to a response to indicate that a page should never be cached.
    """
    patch_response_headers(response, cache_timeout=-1)
    patch_cache_control(
        response, no_cache=True, no_store=True, must_revalidate=True, private=True
    )


def patch_cache_control(
    response: Response,
    *,
    max_age: int | None = None,
    s_maxage: int | None = None,
    stale_while_revalidate: int | None = None,
    stale_if_error: int | None = None,
    no_cache: bool = False,
    no_store: bool = False,
    no_transform: bool = False,
    must_revalidate: bool = False,
    proxy_revalidate: bool = False,
    must_understand: bool = False,
    public: bool = False,
    private: bool = False,
    immutable: bool = False,
) -> None:
    """
    Patch the Cache-Control header on the response, merging the given
    directives with any already present.

    Parameter names map to their hyphenated Cache-Control directives
    (``max_age`` -> ``max-age``). Integer directives are emitted as
    ``name=value`` when set; boolean directives are emitted as a bare
    directive name when True. If ``max-age`` is already present, the smaller of
    the existing and new value wins (this happens when a decorator and a piece
    of middleware both operate on a given view). Setting ``public`` clears an
    existing ``private`` directive and vice versa.
    """

    def dictitem(s: str) -> tuple[str, str | bool]:
        t = s.split("=", 1)
        if len(t) > 1:
            return (t[0].lower(), t[1])
        else:
            return (t[0].lower(), True)

    def dictvalue(directive: str, value: str | bool) -> str:
        if value is True:
            return directive
        else:
            return f"{directive}={value}"

    # Collect the requested directives under their hyphenated names.
    new: dict[str, int | bool] = {}
    for directive, number in (
        ("max-age", max_age),
        ("s-maxage", s_maxage),
        ("stale-while-revalidate", stale_while_revalidate),
        ("stale-if-error", stale_if_error),
    ):
        if number is not None:
            new[directive] = number
    for directive, flag in (
        ("no-cache", no_cache),
        ("no-store", no_store),
        ("no-transform", no_transform),
        ("must-revalidate", must_revalidate),
        ("proxy-revalidate", proxy_revalidate),
        ("must-understand", must_understand),
        ("public", public),
        ("private", private),
        ("immutable", immutable),
    ):
        if flag:
            new[directive] = True

    cc: defaultdict[str, Any] = defaultdict(set)
    if response.headers.get("Cache-Control"):
        for field in _cc_delim_re.split(response.headers["Cache-Control"]):
            directive, value = dictitem(field)
            if directive == "no-cache":
                # no-cache supports multiple field names.
                cc[directive].add(value)
            else:
                cc[directive] = value

    # If there's already a max-age header but we're being asked to set a new
    # max-age, use the minimum of the two ages.
    if "max-age" in cc and "max-age" in new:
        new["max-age"] = min(int(cc["max-age"]), int(new["max-age"]))

    # Allow overriding private caching and vice versa.
    if "private" in cc and "public" in new:
        del cc["private"]
    elif "public" in cc and "private" in new:
        del cc["public"]

    for directive, value in new.items():
        if directive == "no-cache":
            # no-cache supports multiple field names.
            cc[directive].add(value)
        else:
            cc[directive] = value

    directives = []
    for directive, values in cc.items():
        if isinstance(values, set):
            if True in values:
                # True takes precedence.
                values = {True}
            directives.extend([dictvalue(directive, value) for value in values])
        else:
            directives.append(dictvalue(directive, values))
    response.headers["Cache-Control"] = ", ".join(directives)


def patch_vary_headers(response: Response, newheaders: list[str]) -> None:
    """
    Add (or update) the "Vary" header in the given Response object.
    newheaders is a list of header names that should be in "Vary". If headers
    contains an asterisk, then "Vary" header will consist of a single asterisk
    '*'. Otherwise, existing headers in "Vary" aren't removed.
    """
    # Note that we need to keep the original order intact, because cache
    # implementations may rely on the order of the Vary contents in, say,
    # computing an MD5 hash.
    if "Vary" in response.headers:
        vary_headers = _cc_delim_re.split(response.headers["Vary"])
    else:
        vary_headers = []
    # Use .lower() here so we treat headers as case-insensitive.
    existing_headers = {header.lower() for header in vary_headers}
    additional_headers = [
        newheader
        for newheader in newheaders
        if newheader.lower() not in existing_headers
    ]
    vary_headers += additional_headers
    if "*" in vary_headers:
        response.headers["Vary"] = "*"
    else:
        response.headers["Vary"] = ", ".join(vary_headers)
