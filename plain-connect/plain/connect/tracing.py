from __future__ import annotations

from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.trace import format_trace_id


@dataclass(frozen=True)
class CurrentTrace:
    """The active request's OpenTelemetry trace, as connect needs it.

    `trace_id` is the 32-char hex id, or "" when there is no valid trace —
    connect only installs an SDK tracer provider when export is configured,
    so without a token requests get no-op spans with an all-zero id.

    `sampled` is the final sampling decision (so a sub-1.0
    CONNECT_TRACE_SAMPLE_RATE is accounted for here for free), or None when
    there is no valid trace.
    """

    trace_id: str
    sampled: bool | None


def current_trace() -> CurrentTrace:
    """Read the active span's trace id and sampling decision."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return CurrentTrace(trace_id="", sampled=None)
    return CurrentTrace(
        trace_id=format_trace_id(span_context.trace_id),
        sampled=span_context.trace_flags.sampled,
    )
