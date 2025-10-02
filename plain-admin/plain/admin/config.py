from plain.packages import PackageConfig, packages_registry, register_config


@register_config
class Config(PackageConfig):
    package_label = "plainadmin"

    def ready(self) -> None:
        # Trigger register calls to fire by importing the modules
        packages_registry.autodiscover_modules("admin", include_app=True)
