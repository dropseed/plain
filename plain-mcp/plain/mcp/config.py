from __future__ import annotations

from plain.packages import PackageConfig, packages_registry, register_config


@register_config
class Config(PackageConfig):
    package_label = "plainmcp"

    def ready(self) -> None:
        packages_registry.autodiscover_modules("mcp", include_app=True)
