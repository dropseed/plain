from .checks import PreflightCheck
from .registry import register_check, run_checks
from .results import PreflightResult

# Import these to force registration of checks
import plain.preflight.files  # NOQA isort:skip
import plain.preflight.security  # NOQA isort:skip
import plain.preflight.settings  # NOQA isort:skip
import plain.preflight.urls  # NOQA isort:skip


__all__ = [
    "PreflightCheck",
    "PreflightResult",
    "register_check",
    "run_checks",
]
