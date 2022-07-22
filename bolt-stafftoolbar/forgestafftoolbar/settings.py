from django.conf import settings

from .links import StaffToolbarLink


def get_STAFFTOOLBAR_LINKS():
    return getattr(
        settings,
        "STAFFTOOLBAR_LINKS",
        [
            StaffToolbarLink(text="Admin", url="admin:index"),
        ],
    )


def get_STAFFTOOLBAR_CONTAINER_CLASS():
    return getattr(settings, "STAFFTOOLBAR_CONTAINER_CLASS", "container px-4 mx-auto")


def __getattr__(name):
    """
    Allows settings to be accessed as settings.SETTING_NAME, just like django.conf.
    This makes the logic happen at "runtime" rather than when the settings module is imported.
    """
    func_name = "get_" + name
    funcs = globals()

    if func_name in funcs:
        return funcs[func_name]()

    raise AttributeError(f"{__name__} has no setting named {name}")
