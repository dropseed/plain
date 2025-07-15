import logging
import re

from opentelemetry import baggage
from opentelemetry.sdk.trace import sampling
from opentelemetry.semconv.attributes import url_attributes
from opentelemetry.trace import SpanKind

from plain.http.cookie import unsign_cookie_value
from plain.runtime import settings

logger = logging.getLogger(__name__)


class ObserverSampler(sampling.Sampler):
    """Samples traces based on request path and cookies."""

    def __init__(self):
        # Custom parent-based sampler
        self._delegate = sampling.ParentBased(sampling.ALWAYS_OFF)

        # TODO ignore url namespace instead? admin, observer, assets
        self._ignore_url_paths = [
            re.compile(p) for p in settings.OBSERVER_IGNORE_URL_PATTERNS
        ]

    def should_sample(
        self,
        parent_context,
        trace_id,
        name,
        kind: SpanKind | None = None,
        attributes=None,
        links=None,
        trace_state=None,
    ):
        # First, drop if the URL should be ignored.
        if attributes:
            if url_path := attributes.get(url_attributes.URL_PATH, ""):
                for pattern in self._ignore_url_paths:
                    if pattern.match(url_path):
                        return sampling.SamplingResult(
                            sampling.Decision.DROP,
                            attributes=attributes,
                        )

        # If no processor decision, check cookies directly for root spans
        decision = None
        if parent_context:
            # Check cookies for sampling decision
            if cookies := baggage.get_baggage("http.request.cookies", parent_context):
                if observer_cookie := cookies.get("observer"):
                    unsigned_value = unsign_cookie_value(
                        "observer", observer_cookie, default=False
                    )

                    if unsigned_value in ("sample", "view"):
                        # Always use RECORD_AND_SAMPLE so ParentBased works correctly
                        # The exporter will check the span attribute to decide whether to export
                        decision = sampling.Decision.RECORD_AND_SAMPLE
                    else:
                        decision = sampling.Decision.DROP

        # If no decision from cookies, use default
        if decision is None:
            result = self._delegate.should_sample(
                parent_context,
                trace_id,
                name,
                kind=kind,
                attributes=attributes,
                links=links,
                trace_state=trace_state,
            )
            decision = result.decision

        return sampling.SamplingResult(
            decision,
            attributes=attributes,
        )

    def get_description(self) -> str:
        return "ObserverSampler"
