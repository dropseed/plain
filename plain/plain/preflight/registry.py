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
