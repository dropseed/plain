from functools import wraps

from django.utils.cache import add_never_cache_headers, patch_cache_control


def cache_control(**kwargs):
    def _cache_controller(viewfunc):
        @wraps(viewfunc)
        def _cache_controlled(request, *args, **kw):
            # Ensure argument looks like a request.
            if not hasattr(request, "META"):
                raise TypeError(
                    "cache_control didn't receive an HttpRequest. If you are "
                    "decorating a classmethod, be sure to use "
                    "@method_decorator."
                )
            response = viewfunc(request, *args, **kw)
            patch_cache_control(response, **kwargs)
            return response

        return _cache_controlled

    return _cache_controller


def never_cache(view_func):
    """
    Decorator that adds headers to a response so that it will never be cached.
    """

    @wraps(view_func)
    def _wrapper_view_func(request, *args, **kwargs):
        # Ensure argument looks like a request.
        if not hasattr(request, "META"):
            raise TypeError(
                "never_cache didn't receive an HttpRequest. If you are "
                "decorating a classmethod, be sure to use @method_decorator."
            )
        response = view_func(request, *args, **kwargs)
        add_never_cache_headers(response)
        return response

    return _wrapper_view_func
