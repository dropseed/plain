from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from plain.packages import PackageConfig, register_config

from .processor import ObserverSpanProcessor
from .sampler import ObserverSampler


@register_config
class Config(PackageConfig):
    package_label = "plainobserver"

    def ready(self):
        if self.has_existing_trace_provider():
            return

        self.setup_observer()

    @staticmethod
    def has_existing_trace_provider() -> bool:
        """Check if there is an existing trace provider."""
        current_provider = trace.get_tracer_provider()
        return current_provider and not isinstance(
            current_provider, trace.ProxyTracerProvider
        )

    @staticmethod
    def setup_observer() -> None:
        sampler = ObserverSampler()
        provider = TracerProvider(sampler=sampler)

        # Add our combined processor that handles both memory storage and export
        observer_processor = ObserverSpanProcessor()
        provider.add_span_processor(observer_processor)

        trace.set_tracer_provider(provider)
