import re
import threading

from opentelemetry import baggage
from opentelemetry.sdk.trace import sampling
from opentelemetry.semconv.attributes import url_attributes
from opentelemetry.trace import SpanKind

from plain.http.cookie import unsign_cookie_value
from plain.runtime import settings


class ObserverSampler(sampling.Sampler):
    """Drops traces based on request path or user role."""

    def __init__(self):
        # Custom parent-based sampler that properly handles RECORD_ONLY inheritance
        self._delegate = sampling.ParentBased(sampling.ALWAYS_OFF)

        # TODO ignore url namespace instead? admin, observer, assets
        self._ignore_url_paths = [
            re.compile(p) for p in settings.OBSERVER_IGNORE_URL_PATTERNS
        ]

        # Track sampling decisions by trace ID
        self._trace_decisions = {}  # trace_id -> Decision
        self._lock = threading.Lock()

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

        # Check if we already have a decision for this trace
        with self._lock:
            if trace_id in self._trace_decisions:
                decision = self._trace_decisions[trace_id]
                return sampling.SamplingResult(
                    decision,
                    attributes=attributes,
                )

        # For new traces, check cookies in the context
        decision = None
        if parent_context:
            # Check cookies for root spans
            if cookies := baggage.get_baggage("http.request.cookies", parent_context):
                if observer_cookie := cookies.get("observer"):
                    unsigned_value = unsign_cookie_value(
                        "observer", observer_cookie, default=False
                    )

                    if unsigned_value == "sample":
                        decision = sampling.Decision.RECORD_AND_SAMPLE
                    elif unsigned_value == "record":
                        decision = sampling.Decision.RECORD_ONLY

                if decision is None:
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

        # Store the decision for this trace
        with self._lock:
            self._trace_decisions[trace_id] = decision
            # Clean up old entries if too many (simple LRU)
            if len(self._trace_decisions) > 1000:
                # Remove oldest entries
                for old_trace_id in list(self._trace_decisions.keys())[:100]:
                    del self._trace_decisions[old_trace_id]

        return sampling.SamplingResult(
            decision,
            attributes=attributes,
        )

    def get_description(self) -> str:
        return "ObserverSampler"
