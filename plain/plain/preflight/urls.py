from __future__ import annotations

from .checks import PreflightCheck
from .registry import register_check
from .results import PreflightResult


@register_check("urls.config")
class CheckUrlConfig(PreflightCheck):
    """Validates the URL configuration for common issues."""

    def run(self) -> list[PreflightResult]:
        from plain.urls import get_resolver

        resolver = get_resolver()
        return resolver.preflight()
