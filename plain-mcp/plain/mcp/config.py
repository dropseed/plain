from __future__ import annotations

from plain.packages import PackageConfig, register_config


@register_config
class Config(PackageConfig):
    package_label = "plainmcp"
