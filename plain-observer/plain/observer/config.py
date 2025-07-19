from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from plain.packages import PackageConfig, register_config

from .otel import (
    ObserverCombinedSampler,
    ObserverSampler,
    ObserverSpanProcessor,
    get_observer_span_processor,
)


@register_config
class Config(PackageConfig):
    package_label = "plainobserver"

    def ready(self):
        sampler = ObserverSampler()
        span_processor = ObserverSpanProcessor()

        if provider := self.get_existing_trace_provider():
            # There is already a trace provider, so combine our sampler
            # and add an additional span processor for Observer
            if hasattr(provider, "sampler"):
                provider.sampler = ObserverCombinedSampler(provider.sampler, sampler)

            if not get_observer_span_processor():
                provider.add_span_processor(span_processor)
        else:
            # Start our own provider, new sampler, and span processor
            provider = TracerProvider(sampler=sampler)
            provider.add_span_processor(span_processor)
            trace.set_tracer_provider(provider)

    @staticmethod
    def get_existing_trace_provider():
        """Return the currently configured provider if set."""
        current_provider = trace.get_tracer_provider()
        if current_provider and not isinstance(
            current_provider, trace.ProxyTracerProvider
        ):
            return current_provider
        return None
