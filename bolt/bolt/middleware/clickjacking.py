"""
Clickjacking Protection Middleware.

This module provides a middleware that implements protection against a
malicious site loading resources from your site in a hidden frame.
"""

from bolt.runtime import settings


class XFrameOptionsMiddleware:
    """
    Set the X-Frame-Options HTTP header in HTTP responses.

    Do not set the header if it's already set or if the response contains
    a xframe_options_exempt value set to True.

    By default, set the X-Frame-Options header to 'DENY', meaning the response
    cannot be displayed in a frame, regardless of the site attempting to do so.
    To enable the response to be loaded on a frame within the same site, set
    X_FRAME_OPTIONS in your project's Plain settings to 'SAMEORIGIN'.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Don't set it if it's already in the response
        if response.get("X-Frame-Options") is not None:
            return response

        # Don't set it if they used @xframe_options_exempt
        if getattr(response, "xframe_options_exempt", False):
            return response

        response.headers["X-Frame-Options"] = self.get_xframe_options_value(
            request,
            response,
        )
        return response

    def get_xframe_options_value(self, request, response):
        """
        Get the value to set for the X_FRAME_OPTIONS header. Use the value from
        the X_FRAME_OPTIONS setting, or 'DENY' if not set.

        This method can be overridden if needed, allowing it to vary based on
        the request or response.
        """
        return getattr(settings, "X_FRAME_OPTIONS", "DENY").upper()
