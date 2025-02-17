import logging
import types

from plain.exceptions import ImproperlyConfigured
from plain.logs import log_response
from plain.runtime import settings
from plain.urls import get_resolver
from plain.utils.module_loading import import_string

from .exception import convert_exception_to_response

logger = logging.getLogger("plain.request")


# These middleware classes are always used by Plain.
BUILTIN_BEFORE_MIDDLEWARE = [
    "plain.internal.middleware.headers.DefaultHeadersMiddleware",  # Runs after response, to set missing headers
    "plain.internal.middleware.https.HttpsRedirectMiddleware",  # Runs before response, to redirect to HTTPS quickly
    "plain.csrf.middleware.CsrfViewMiddleware",  # Runs before and after get_response...
]

BUILTIN_AFTER_MIDDLEWARE = [
    # Want this to run first (when reversed) so the slash middleware
    # can immediately redirect to the slash-appended path if there is one.
    "plain.internal.middleware.slash.RedirectSlashMiddleware",
]


class BaseHandler:
    _middleware_chain = None

    def load_middleware(self):
        """
        Populate middleware lists from settings.MIDDLEWARE.

        Must be called after the environment is fixed (see __call__ in subclasses).
        """
        get_response = self._get_response
        handler = convert_exception_to_response(get_response)

        middlewares = reversed(
            BUILTIN_BEFORE_MIDDLEWARE + settings.MIDDLEWARE + BUILTIN_AFTER_MIDDLEWARE
        )

        for middleware_path in middlewares:
            middleware = import_string(middleware_path)
            mw_instance = middleware(handler)

            if mw_instance is None:
                raise ImproperlyConfigured(
                    f"Middleware factory {middleware_path} returned None."
                )

            handler = convert_exception_to_response(mw_instance)

        # We only assign to this when initialization is complete as it is used
        # as a flag for initialization being complete.
        self._middleware_chain = handler

    def get_response(self, request):
        """Return a Response object for the given HttpRequest."""
        # Setup default url resolver for this thread
        response = self._middleware_chain(request)
        response._resource_closers.append(request.close)
        if response.status_code >= 400:
            log_response(
                "%s: %s",
                response.reason_phrase,
                request.path,
                response=response,
                request=request,
            )
        return response

    def _get_response(self, request):
        """
        Resolve and call the view, then apply view, exception, and
        template_response middleware. This method is everything that happens
        inside the request/response middleware.
        """
        resolver_match = self.resolve_request(request)

        response = resolver_match.func(
            request, *resolver_match.args, **resolver_match.kwargs
        )

        # Complain if the view returned None (a common error).
        self.check_response(response, resolver_match.func)

        return response

    def resolve_request(self, request):
        """
        Retrieve/set the urlrouter for the request. Return the view resolved,
        with its args and kwargs.
        """
        resolver = get_resolver()
        # Resolve the view, and assign the match object back to the request.
        resolver_match = resolver.resolve(request.path_info)
        request.resolver_match = resolver_match
        return resolver_match

    def check_response(self, response, callback, name=None):
        """
        Raise an error if the view returned None or an uncalled coroutine.
        """
        if not name:
            if isinstance(callback, types.FunctionType):  # FBV
                name = f"The view {callback.__module__}.{callback.__name__}"
            else:  # CBV
                name = f"The view {callback.__module__}.{callback.__class__.__name__}.__call__"
        if response is None:
            raise ValueError(
                f"{name} didn't return a Response object. It returned None instead."
            )
