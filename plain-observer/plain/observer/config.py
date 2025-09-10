from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.semconv.attributes import service_attributes

from plain.logs import app_logger
from plain.packages import PackageConfig, register_config
from plain.runtime import settings

from .logging import observer_log_handler
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
            resource = Resource.create(
                {
                    service_attributes.SERVICE_NAME: settings.APP_NAME,
                    service_attributes.SERVICE_VERSION: settings.APP_VERSION,
                }
            )
            provider = TracerProvider(sampler=sampler, resource=resource)
            provider.add_span_processor(span_processor)
            trace.set_tracer_provider(provider)

        # Install the logging handler to capture logs during traces
        if observer_log_handler not in app_logger.handlers:
            # Copy formatter from existing app_logger handler to match log formatting
            for handler in app_logger.handlers:
                if handler.formatter:
                    observer_log_handler.setFormatter(handler.formatter)
                    break

            app_logger.addHandler(observer_log_handler)

    @staticmethod
    def get_existing_trace_provider():
        """Return the currently configured provider if set."""
        current_provider = trace.get_tracer_provider()
        if current_provider and not isinstance(
            current_provider, trace.ProxyTracerProvider
        ):
            return current_provider
        return None
