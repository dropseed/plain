from __future__ import annotations

from collections.abc import Callable, Generator, Iterable
from typing import Any, TypeVar

from plain.runtime import settings

from .checks import PreflightCheck
from .results import PreflightResult, unused_silenced_results

T = TypeVar("T")

UNUSED_SILENCES_CHECK_NAME = "preflight.unused_silences"


class CheckUnusedSilences(PreflightCheck):
    """Reports `PREFLIGHT_SILENCED_RESULTS` entries that matched nothing.

    An unused entry is either a typo or stale — the issue it silenced has
    been fixed. Not registered like a normal check: it needs every other
    check's results, so the registry runs it last with the full run's
    results, and only on a full run (deploy checks included) — a partial
    run skips checks whose entries would then look unused.
    """

    def __init__(self, run_results: list[PreflightResult]) -> None:
        self.run_results = run_results

    def run(self) -> list[PreflightResult]:
        return [
            PreflightResult(
                fix=f"Silenced result {entry!r} matched nothing in this run. "
                "Remove it from PREFLIGHT_SILENCED_RESULTS or fix the typo.",
                obj=entry,
                id="preflight.unused_silence",
                warning=True,
            )
            for entry in unused_silenced_results(self.run_results)
        ]


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
        # Validate silenced check names (the unused-silences check isn't in
        # self.checks — the registry emits it itself — but it's silenceable
        # like any other check)
        silenced_checks = settings.PREFLIGHT_SILENCED_CHECKS
        known_checks = set(self.checks.keys()) | {UNUSED_SILENCES_CHECK_NAME}
        unknown_silenced = set(silenced_checks) - known_checks
        if unknown_silenced:
            unknown_names = ", ".join(sorted(unknown_silenced))
            raise ValueError(
                f"Unknown check names in PREFLIGHT_SILENCED_CHECKS: {unknown_names}. "
                "Check for typos or remove outdated check names."
            )

        all_results: list[PreflightResult] = []

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
            all_results.extend(results)
            yield check_class, name, results

        if include_deploy_checks and UNUSED_SILENCES_CHECK_NAME not in silenced_checks:
            check = CheckUnusedSilences(all_results)
            yield CheckUnusedSilences, UNUSED_SILENCES_CHECK_NAME, check.run()


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


def count_results_by_severity(
    checks: Iterable[tuple[Any, str, list[PreflightResult]]],
) -> tuple[int, int]:
    """Tally ``(errors, warnings)`` across checks by each check's *visible*
    (non-silenced) issues. A check with no visible issues counts as neither —
    an error if any visible issue isn't a warning, otherwise a warning."""
    error_count = 0
    warning_count = 0
    for _check_class, _name, results in checks:
        visible = [r for r in results if not r.is_silenced()]
        if not visible:
            continue
        if any(not r.warning for r in visible):
            error_count += 1
        else:
            warning_count += 1
    return error_count, warning_count


def get_check_counts() -> dict[str, int]:
    """Return ``{"errors": N, "warnings": N}``, caching for the process lifetime."""
    global _check_counts

    if _check_counts is not None:
        return _check_counts

    from plain.packages import packages_registry

    packages_registry.autodiscover_modules("preflight", include_app=True)

    error_count, warning_count = count_results_by_severity(
        run_checks(include_deploy_checks=not settings.DEBUG)
    )

    _check_counts = {"errors": error_count, "warnings": warning_count}
    return _check_counts


def set_check_counts(*, errors: int, warnings: int) -> None:
    """Update the cached counts (called by PreflightView after running full checks)."""
    global _check_counts
    _check_counts = {"errors": errors, "warnings": warnings}
