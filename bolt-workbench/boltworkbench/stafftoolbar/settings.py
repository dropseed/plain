from django.conf import settings

from .links import StaffToolbarLink


def STAFFTOOLBAR_LINKS():
    return getattr(
        settings,
        "STAFFTOOLBAR_LINKS",
        [
            StaffToolbarLink(text="Admin", url="admin:index"),
        ],
    )
