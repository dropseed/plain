"""OTel-related helpers shared across Plain packages."""

from __future__ import annotations


def format_exception_type(exc: BaseException) -> str:
    """Format an exception's class name per OTel semantic conventions.

    Returns the fully-qualified class name (``module.qualname``) for
    third-party and user-defined exceptions. Python builtins drop the
    ``builtins.`` prefix so common exceptions stay short.

    Used for the ``error.type`` span attribute, which SHOULD match the
    ``exception.type`` attribute written by ``span.record_exception()``.

    Examples::

        ValueError                      -> "ValueError"
        django.db.utils.IntegrityError  -> "django.db.utils.IntegrityError"
        myapp.errors.BillingError       -> "myapp.errors.BillingError"
    """
    cls = type(exc)
    if cls.__module__ == "builtins":
        return cls.__qualname__
    return f"{cls.__module__}.{cls.__qualname__}"
