import re

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, sampling
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from plain.packages import PackageConfig, register_config
from plain.runtime import settings

from .otel import ObserveModelsExporter, PlainRequestSampler


@register_config
class Config(PackageConfig):
    package_label = "plainobserve"

    def ready(self):
        current_provider = trace.get_tracer_provider()
        if current_provider and not isinstance(
            current_provider, trace.ProxyTracerProvider
        ):
            return

        ignore_url_patterns = [re.compile(p) for p in settings.OBSERVE_IGNORE_URLS]

        sampler = PlainRequestSampler(
            sampling.ParentBased(sampling.ALWAYS_ON), ignore_url_patterns
        )
        provider = TracerProvider(sampler=sampler)
        provider.add_span_processor(BatchSpanProcessor(ObserveModelsExporter()))
        trace.set_tracer_provider(provider)
