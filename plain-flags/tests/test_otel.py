"""OTel instrumentation tests for feature flag evaluation.

The flag evaluation span uses OTel-semconv `feature_flag.*` attributes;
these tests guard against drift in the attribute names and `result.reason`
values that downstream dashboards may filter on.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from plain.flags import Flag


class _KeyedFlag(Flag):
    def get_key(self):
        return "user-123"

    def get_value(self):
        return True


class _UnkeyedFlag(Flag):
    def get_key(self):
        return None

    def get_value(self):
        return "feature-on"


@pytest.mark.usefixtures("db")
def test_first_eval_with_key_emits_targeting_match_reason(
    otel_spans: InMemorySpanExporter,
) -> None:
    flag = _KeyedFlag()
    assert flag.value is True

    span = next(
        s for s in otel_spans.get_finished_spans() if s.name == "flag _KeyedFlag"
    )
    attrs = span.attributes
    assert attrs is not None
    assert attrs["feature_flag.provider.name"] == "plain.flags"
    assert attrs["feature_flag.key"] == "user-123"
    # `get_value()` ran dynamically with this key — semconv `targeting_match`,
    # not `static` (which means "no dynamic evaluation").
    assert attrs["feature_flag.result.reason"] == "targeting_match"
    assert attrs["feature_flag.result.value"] == "True"


@pytest.mark.usefixtures("db")
def test_second_eval_with_key_emits_cached_reason(
    otel_spans: InMemorySpanExporter,
) -> None:
    # First eval persists a FlagResult row; second eval (separate instance,
    # no cached_property to bypass) should hit the cached path.
    _KeyedFlag().retrieve_or_compute_value()
    otel_spans.clear()

    _KeyedFlag().retrieve_or_compute_value()

    span = next(
        s for s in otel_spans.get_finished_spans() if s.name == "flag _KeyedFlag"
    )
    attrs = span.attributes
    assert attrs is not None
    assert attrs["feature_flag.result.reason"] == "cached"
    assert attrs["feature_flag.key"] == "user-123"


@pytest.mark.usefixtures("db")
def test_unkeyed_flag_emits_targeting_match_reason(
    otel_spans: InMemorySpanExporter,
) -> None:
    flag = _UnkeyedFlag()
    assert flag.value == "feature-on"

    span = next(
        s for s in otel_spans.get_finished_spans() if s.name == "flag _UnkeyedFlag"
    )
    attrs = span.attributes
    assert attrs is not None
    assert attrs["feature_flag.result.reason"] == "targeting_match"
    assert attrs["feature_flag.result.value"] == "feature-on"
    assert "feature_flag.key" not in attrs


@pytest.mark.usefixtures("db")
def test_disabled_flag_emits_disabled_reason_with_key(
    otel_spans: InMemorySpanExporter,
    settings,
) -> None:
    from plain.flags.models import Flag as FlagModel

    # Pre-create a disabled DB row for the flag class.
    FlagModel.query.create(name="_KeyedFlag", enabled=False)
    settings.DEBUG = False  # disabled flags raise in DEBUG; we want the log path

    assert _KeyedFlag().value is None

    span = next(
        s for s in otel_spans.get_finished_spans() if s.name == "flag _KeyedFlag"
    )
    attrs = span.attributes
    assert attrs is not None
    assert attrs["feature_flag.result.reason"] == "disabled"
    # The key is resolved before the disabled check, so dashboards filtering
    # disabled events by user/tenant key still see the evaluation.
    assert attrs["feature_flag.key"] == "user-123"
