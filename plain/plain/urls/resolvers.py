"""
This module converts requested URLs to callback view functions.

URLResolver is the main class here. Its resolve() method takes a URL (as
a string) and returns a ResolverMatch object which provides access to all
attributes of the resolved URL match.
"""

from __future__ import annotations

import functools
import re
from threading import local
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from plain.runtime import settings
from plain.utils.datastructures import MultiValueDict
from plain.utils.http import RFC3986_SUBDELIMS, escape_leading_slashes
from plain.utils.module_loading import import_string
from plain.utils.regex_helper import _normalize

from .exceptions import NoReverseMatch, Resolver404
from .patterns import RegexPattern, RoutePattern, URLPattern

if TYPE_CHECKING:
    from plain.preflight import PreflightResult

    from .routers import Router


class ResolverMatch:
    def __init__(
        self,
        *,
        view: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        url_name: str | None = None,
        namespaces: list[str] | None = None,
        route: str | None = None,
    ):
        self.view = view
        self.args = args
        self.kwargs = kwargs
        self.url_name = url_name
        self.route = route

        # If a URLRegexResolver doesn't have a namespace or namespace, it passes
        # in an empty value.
        self.namespaces = [x for x in namespaces if x] if namespaces else []
        self.namespace = ":".join(self.namespaces)

        self.namespaced_url_name = (
            ":".join(self.namespaces + [url_name]) if url_name else None
        )


def get_resolver(router: str | Router | None = None) -> URLResolver:
    if router is None:
        router = settings.URLS_ROUTER

    return _get_cached_resolver(router)


@functools.cache
def _get_cached_resolver(router: str | Router) -> URLResolver:
    if isinstance(router, str):
        # Do this inside the cached call, primarily for the URLS_ROUTER
        router_class = import_string(router)
        router = router_class()

    return URLResolver(pattern=RegexPattern(r"^/"), router=router)


@functools.cache
def get_ns_resolver(
    ns_pattern: str, resolver: URLResolver, converters: tuple[tuple[str, Any], ...]
) -> URLResolver:
    from .routers import Router

    # Build a namespaced resolver for the given parent urls_module pattern.
    # This makes it possible to have captured parameters in the parent
    # urls_module pattern.
    pattern = RegexPattern(ns_pattern)
    pattern.converters = dict(converters)

    class _NestedRouter(Router):
        namespace = ""
        urls = resolver.url_patterns

    ns_resolver = URLResolver(pattern=pattern, router=_NestedRouter())

    class _NamespacedRouter(Router):
        namespace = ""
        urls = [ns_resolver]

    return URLResolver(
        pattern=RegexPattern(r"^/"),
        router=_NamespacedRouter(),
    )


class URLResolver:
    def __init__(
        self,
        *,
        pattern: RegexPattern | RoutePattern,
        router: Router,
    ):
        self.pattern = pattern
        self.router = router
        self._reverse_dict: MultiValueDict = MultiValueDict()
        self._namespace_dict: dict[str, tuple[str, URLResolver]] = {}
        self._populated = False
        self._local = local()

        # Set these immediately, in part so we can find routers
        # where the attributes weren't set correctly.
        self.namespace = self.router.namespace
        self.url_patterns = self.router.urls

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {repr(self.router)} ({self.namespace}) {self.pattern.describe()}>"

    def preflight(self) -> list[PreflightResult]:
        messages = []
        messages.extend(self.pattern.preflight())
        for pattern in self.url_patterns:
            messages.extend(pattern.preflight())
        return messages

    def _populate(self) -> None:
        # Short-circuit if called recursively in this thread to prevent
        # infinite recursion. Concurrent threads may call this at the same
        # time and will need to continue, so set 'populating' on a
        # thread-local variable.
        if getattr(self._local, "populating", False):
            return
        try:
            self._local.populating = True
            lookups = MultiValueDict()
            namespaces = {}
            for url_pattern in reversed(self.url_patterns):
                p_pattern = url_pattern.pattern.regex.pattern
                p_pattern = p_pattern.removeprefix("^")
                if isinstance(url_pattern, URLPattern):
                    bits = _normalize(url_pattern.pattern.regex.pattern)
                    lookups.appendlist(
                        url_pattern.view,
                        (
                            bits,
                            p_pattern,
                            url_pattern.pattern.converters,
                        ),
                    )
                    if url_pattern.name is not None:
                        lookups.appendlist(
                            url_pattern.name,
                            (
                                bits,
                                p_pattern,
                                url_pattern.pattern.converters,
                            ),
                        )
                else:  # url_pattern is a URLResolver.
                    url_pattern._populate()
                    if url_pattern.namespace:
                        namespaces[url_pattern.namespace] = (p_pattern, url_pattern)
                    else:
                        for name in url_pattern.reverse_dict:
                            for (
                                _,
                                pat,
                                converters,
                            ) in url_pattern.reverse_dict.getlist(name):
                                new_matches = _normalize(p_pattern + pat)
                                lookups.appendlist(
                                    name,
                                    (
                                        new_matches,
                                        p_pattern + pat,
                                        {
                                            **self.pattern.converters,
                                            **url_pattern.pattern.converters,
                                            **converters,
                                        },
                                    ),
                                )
                        for namespace, (
                            prefix,
                            sub_pattern,
                        ) in url_pattern.namespace_dict.items():
                            current_converters = url_pattern.pattern.converters
                            sub_pattern.pattern.converters.update(current_converters)
                            namespaces[namespace] = (p_pattern + prefix, sub_pattern)
            self._namespace_dict = namespaces
            self._reverse_dict = lookups
            self._populated = True
        finally:
            self._local.populating = False

    @property
    def reverse_dict(self) -> MultiValueDict:
        if not self._reverse_dict:
            self._populate()
        return self._reverse_dict

    @property
    def namespace_dict(self) -> dict[str, tuple[str, URLResolver]]:
        if not self._namespace_dict:
            self._populate()
        return self._namespace_dict

    @staticmethod
    def _join_route(route1: str, route2: str) -> str:
        """Join two routes, without the starting ^ in the second route."""
        if not route1:
            return route2
        route2 = route2.removeprefix("^")
        return route1 + route2

    def resolve(self, path: str) -> ResolverMatch:
        path = str(path)  # path may be a reverse_lazy object
        match = self.pattern.match(path)
        if match:
            new_path, args, kwargs = match
            for pattern in self.url_patterns:
                try:
                    sub_match = pattern.resolve(new_path)
                except Resolver404:
                    pass
                else:
                    if sub_match:
                        # Merge captured arguments in match with submatch
                        # Update the sub_match_dict with the kwargs from the sub_match.
                        sub_match_dict = {**kwargs, **sub_match.kwargs}
                        # If there are *any* named groups, ignore all non-named groups.
                        # Otherwise, pass all non-named arguments as positional
                        # arguments.
                        sub_match_args = sub_match.args
                        if not sub_match_dict:
                            sub_match_args = args + sub_match.args
                        current_route = (
                            ""
                            if isinstance(pattern, URLPattern)
                            else str(pattern.pattern)
                        )
                        return ResolverMatch(
                            view=sub_match.view,
                            args=sub_match_args,
                            kwargs=sub_match_dict,
                            url_name=sub_match.url_name,
                            namespaces=[self.namespace] + sub_match.namespaces,
                            route=self._join_route(current_route, sub_match.route),
                        )
            raise Resolver404({"path": new_path})
        raise Resolver404({"path": path})

    def reverse(self, lookup_view: Any, *args: Any, **kwargs: Any) -> str:
        if args and kwargs:
            raise ValueError("Don't mix *args and **kwargs in call to reverse()!")

        if not self._populated:
            self._populate()

        possibilities = self.reverse_dict.getlist(lookup_view)

        for possibility, pattern, converters in possibilities:
            for result, params in possibility:
                if args:
                    if len(args) != len(params):
                        continue
                    candidate_subs = dict(zip(params, args))
                else:
                    if set(kwargs).symmetric_difference(params):
                        continue
                    candidate_subs = kwargs
                # Convert the candidate subs to text using Converter.to_url().
                text_candidate_subs = {}
                match = True
                for k, v in candidate_subs.items():
                    if k in converters:
                        try:
                            text_candidate_subs[k] = converters[k].to_url(v)
                        except ValueError:
                            match = False
                            break
                    else:
                        text_candidate_subs[k] = str(v)
                if not match:
                    continue
                # WSGI provides decoded URLs, without %xx escapes, and the URL
                # resolver operates on such URLs. First substitute arguments
                # without quoting to build a decoded URL and look for a match.
                # Then, if we have a match, redo the substitution with quoted
                # arguments in order to return a properly encoded URL.

                # There was a lot of script_prefix handling code before,
                # so this is a crutch to leave the below as-is for now.
                _prefix = "/"

                candidate_pat = _prefix.replace("%", "%%") + result
                if re.search(
                    f"^{re.escape(_prefix)}{pattern}",
                    candidate_pat % text_candidate_subs,
                ):
                    # safe characters from `pchar` definition of RFC 3986
                    url = quote(
                        candidate_pat % text_candidate_subs,
                        safe=RFC3986_SUBDELIMS + "/~:@",
                    )
                    # Don't allow construction of scheme relative urls.
                    return escape_leading_slashes(url)
        # lookup_view can be URL name or callable, but callables are not
        # friendly in error messages.
        m = getattr(lookup_view, "__module__", None)
        n = getattr(lookup_view, "__name__", None)
        if m is not None and n is not None:
            lookup_view_s = f"{m}.{n}"
        else:
            lookup_view_s = lookup_view

        patterns = [pos[1] for pos in possibilities]
        if patterns:
            if args:
                arg_msg = f"arguments '{args}'"
            elif kwargs:
                arg_msg = f"keyword arguments '{kwargs}'"
            else:
                arg_msg = "no arguments"
            msg = "Reverse for '%s' with %s not found. %d pattern(s) tried: %s" % (  # noqa: UP031
                lookup_view_s,
                arg_msg,
                len(patterns),
                patterns,
            )
        else:
            msg = (
                f"Reverse for '{lookup_view_s}' not found. '{lookup_view_s}' is not "
                "a valid view function or pattern name."
            )
        raise NoReverseMatch(msg)
