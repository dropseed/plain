from .checks import PreflightCheck
from .registry import register_check


@register_check("urls.config")
class CheckUrlConfig(PreflightCheck):
    """Validates the URL configuration for common issues."""

    def run(self):
        from plain.urls import get_resolver

        resolver = get_resolver()
        return resolver.preflight()
