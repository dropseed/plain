from django.conf import settings

from .links import StaffToolbarLink

STAFFTOOLBAR_LINKS = getattr(
    settings,
    "STAFFTOOLBAR_LINKS",
    [
        StaffToolbarLink(text="Admin", url="admin:index"),
    ],
)

STAFFTOOLBAR_CONTAINER_CLASS = getattr(
    settings, "STAFFTOOLBAR_CONTAINER_CLASS", "container px-4 mx-auto"
)
