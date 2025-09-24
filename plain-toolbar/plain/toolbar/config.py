from plain.packages import PackageConfig, packages_registry, register_config


@register_config
class Config(PackageConfig):
    def ready(self):
        # Trigger register calls to fire by importing the toolbar modules
        packages_registry.autodiscover_modules("toolbar", include_app=True)
