from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from plain.packages import PackageConfig, register_config

from .exporter import ObserverExporter
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

        # Add the real-time span collector for immediate access
        span_collector = ObserverSpanProcessor()
        provider.add_span_processor(span_collector)

        # Add the database exporter using SimpleSpanProcessor for immediate export
        provider.add_span_processor(SimpleSpanProcessor(ObserverExporter()))

        trace.set_tracer_provider(provider)
