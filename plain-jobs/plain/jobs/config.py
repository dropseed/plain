from importlib import import_module

from plain.packages import PackageConfig, packages_registry, register_config

from .registry import jobs_registry


@register_config
class Config(PackageConfig):
    package_label = "plainjobs"

    def ready(self) -> None:
        # Trigger register calls to fire by importing the modules
        packages_registry.autodiscover_modules("jobs", include_app=True)

        # Also need to make sure out internal jobs are registered
        import_module("plain.jobs.scheduling")

        jobs_registry.ready = True
