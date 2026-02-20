from plain.urls import Router, path

from .views import DeviceAuthorizeView, DeviceTokenView

__all__ = ["DeviceFlowRouter"]


class DeviceFlowRouter(Router):
    """
    URL router for the OAuth Device Flow (RFC 8628).

    Include this in your URL config to enable device flow endpoints::

        from plain.api.urls import DeviceFlowRouter

        class AppRouter(Router):
            urls = [
                include("device/", DeviceFlowRouter),
            ]

    This provides:
    - POST /device/authorize/ - Device requests a code pair
    - POST /device/token/ - Device polls for access token
    """

    namespace = "device"
    urls = [
        path("authorize/", DeviceAuthorizeView, name="authorize"),
        path("token/", DeviceTokenView, name="token"),
    ]
