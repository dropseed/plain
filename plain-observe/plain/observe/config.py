from plain.packages import PackageConfig, register_config

from .otel import has_existing_trace_provider, setup_debug_trace_provider


@register_config
class Config(PackageConfig):
    package_label = "plainobserve"

    def ready(self):
        if has_existing_trace_provider():
            return

        setup_debug_trace_provider()
