from plain.runtime import settings

from . import Error, register_check


@register_check
def check_url_config(package_configs, **kwargs):
    if getattr(settings, "URLS_ROUTER", None):
        from plain.urls import get_resolver

        resolver = get_resolver()
        return check_resolver(resolver)

    return []


def check_resolver(resolver):
    """
    Recursively check the resolver.
    """
    check_method = getattr(resolver, "check", None)
    if check_method is not None:
        return check_method()
    elif not hasattr(resolver, "resolve"):
        return get_warning_for_invalid_pattern(resolver)
    else:
        return []


def get_warning_for_invalid_pattern(pattern):
    """
    Return a list containing a warning that the pattern is invalid.

    describe_pattern() cannot be used here, because we cannot rely on the
    urlpattern having regex or name attributes.
    """
    if isinstance(pattern, str):
        hint = (
            f"Try removing the string '{pattern}'. The list of urlpatterns should not "
            "have a prefix string as the first element."
        )
    elif isinstance(pattern, tuple):
        hint = "Try using path() instead of a tuple."
    else:
        hint = None

    return [
        Error(
            f"Your URL pattern {pattern!r} is invalid. Ensure that urlpatterns is a list "
            "of path() and/or re_path() instances.",
            hint=hint,
            id="urls.E004",
        )
    ]
