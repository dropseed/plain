from .messages import (
    CRITICAL,
    DEBUG,
    ERROR,
    INFO,
    WARNING,
    CheckMessage,
    Critical,
    Debug,
    Error,
    Info,
    Warning,
)
from .registry import register, run_checks

# Import these to force registration of checks
import plain.preflight.compatibility.django_4_0  # NOQA isort:skip
import plain.preflight.files  # NOQA isort:skip
import plain.preflight.security.base  # NOQA isort:skip
import plain.preflight.security.csrf  # NOQA isort:skip
import plain.preflight.urls  # NOQA isort:skip


__all__ = [
    "CheckMessage",
    "Debug",
    "Info",
    "Warning",
    "Error",
    "Critical",
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
    "register",
    "run_checks",
]
