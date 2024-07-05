import logging
import types

from plain.exceptions import ImproperlyConfigured
from plain.logs import log_response
from plain.runtime import settings
from plain.signals import request_finished
from plain.urls import get_resolver, set_urlconf
from plain.utils.module_loading import import_string

from .exception import convert_exception_to_response

logger = logging.getLogger("plain.request")


class BaseHandler:
    _view_middleware = None
    _middleware_chain = None

    def load_middleware(self):
        """
        Populate middleware lists from settings.MIDDLEWARE.

        Must be called after the environment is fixed (see __call__ in subclasses).
        """
        self._view_middleware = []

        get_response = self._get_response
        handler = convert_exception_to_response(get_response)
        for middleware_path in reversed(settings.MIDDLEWARE):
            middleware = import_string(middleware_path)
            mw_instance = middleware(handler)

            if mw_instance is None:
                raise ImproperlyConfigured(
                    "Middleware factory %s returned None." % middleware_path
                )

            if hasattr(mw_instance, "process_view"):
                self._view_middleware.insert(
                    0,
                    mw_instance.process_view,
                )

            handler = convert_exception_to_response(mw_instance)

        # We only assign to this when initialization is complete as it is used
        # as a flag for initialization being complete.
        self._middleware_chain = handler

    def get_response(self, request):
        """Return a Response object for the given HttpRequest."""
        # Setup default url resolver for this thread
        set_urlconf(settings.ROOT_URLCONF)
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
        response = None
        callback, callback_args, callback_kwargs = self.resolve_request(request)

        # Apply view middleware
        for middleware_method in self._view_middleware:
            response = middleware_method(
                request, callback, callback_args, callback_kwargs
            )
            if response:
                break

        if response is None:
            response = callback(request, *callback_args, **callback_kwargs)

        # Complain if the view returned None (a common error).
        self.check_response(response, callback)

        return response

    def resolve_request(self, request):
        """
        Retrieve/set the urlconf for the request. Return the view resolved,
        with its args and kwargs.
        """
        # Work out the resolver.
        if hasattr(request, "urlconf"):
            urlconf = request.urlconf
            set_urlconf(urlconf)
            resolver = get_resolver(urlconf)
        else:
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
                name = "The view {}.{}.__call__".format(
                    callback.__module__,
                    callback.__class__.__name__,
                )
        if response is None:
            raise ValueError(
                "%s didn't return a Response object. It returned None "
                "instead." % name
            )


def reset_urlconf(sender, **kwargs):
    """Reset the URLconf after each request is finished."""
    set_urlconf(None)


request_finished.connect(reset_urlconf)
