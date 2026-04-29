from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, TypeVar

from plain.runtime import settings

from .results import PreflightResult

T = TypeVar("T")


class CheckRegistry:
    def __init__(self) -> None:
        self.checks: dict[
            str, tuple[type[Any], bool]
        ] = {}  # name -> (check_class, deploy)

    def register_check(
        self, check_class: type[Any], name: str, deploy: bool = False
    ) -> None:
        """Register a check class with a unique name."""
        if name in self.checks:
            raise ValueError(f"Check {name} already registered")
        self.checks[name] = (check_class, deploy)

    def run_checks(
        self,
        include_deploy_checks: bool = False,
    ) -> Generator[tuple[type[Any], str, list[PreflightResult]]]:
        """
        Run all registered checks and yield (check_class, name, results) tuples.
        """
        # Validate silenced check names
        silenced_checks = settings.PREFLIGHT_SILENCED_CHECKS
        unknown_silenced = set(silenced_checks) - set(self.checks.keys())
        if unknown_silenced:
            unknown_names = ", ".join(sorted(unknown_silenced))
            raise ValueError(
                f"Unknown check names in PREFLIGHT_SILENCED_CHECKS: {unknown_names}. "
                "Check for typos or remove outdated check names."
            )

        for name, (check_class, deploy) in sorted(self.checks.items()):
            # Skip silenced checks
            if name in silenced_checks:
                continue

            # Skip deployment checks if not requested
            if deploy and not include_deploy_checks:
                continue

            # Instantiate and run check
            check = check_class()
            results = check.run()
            yield check_class, name, results

    def get_checks(
        self, include_deploy_checks: bool = False
    ) -> list[tuple[type[Any], str]]:
        """Get list of (check_class, name) tuples."""
        result: list[tuple[type[Any], str]] = []
        for name, (check_class, deploy) in self.checks.items():
            if deploy and not include_deploy_checks:
                continue
            result.append((check_class, name))
        return result


checks_registry = CheckRegistry()


def register_check(name: str, *, deploy: bool = False) -> Callable[[type[T]], type[T]]:
    """
    Decorator to register a check class.

    Usage:
        @register_check("security.secret_key", deploy=True)
        class CheckSecretKey(PreflightCheck):
            pass

        @register_check("files.upload_temp_dir")
        class CheckUploadTempDir(PreflightCheck):
            pass
    """

    def wrapper(cls: type[T]) -> type[T]:
        checks_registry.register_check(cls, name=name, deploy=deploy)
        return cls

    return wrapper


run_checks = checks_registry.run_checks

# Cached error/warning counts — populated on first call, refreshed by
# PreflightView when the full page is viewed.
_check_counts: dict[str, int] | None = None


def iter_check_summaries(*, include_deploy_checks: bool):
    """Yield ``(name, visible_issues, has_errors)`` per registered check.

    Filters silenced results and pre-computes the error-vs-warning split so
    callers don't each reimplement that logic.
    """
    for _check_class, name, results in run_checks(
        include_deploy_checks=include_deploy_checks
    ):
        visible = [r for r in results if not r.is_silenced()]
        has_errors = any(not r.warning for r in visible)
        yield name, visible, has_errors


def get_check_counts() -> dict[str, int]:
    """Return ``{"errors": N, "warnings": N}``, caching for the process lifetime."""
    global _check_counts

    if _check_counts is not None:
        return _check_counts

    from plain.packages import packages_registry

    packages_registry.autodiscover_modules("preflight", include_app=True)

    warning_count = 0
    error_count = 0

    for _name, issues, has_errors in iter_check_summaries(
        include_deploy_checks=not settings.DEBUG
    ):
        if not issues:
            continue
        if has_errors:
            error_count += 1
        else:
            warning_count += 1

    _check_counts = {"errors": error_count, "warnings": warning_count}
    return _check_counts


def set_check_counts(*, errors: int, warnings: int) -> None:
    """Update the cached counts (called by PreflightView after running full checks)."""
    global _check_counts
    _check_counts = {"errors": errors, "warnings": warnings}
