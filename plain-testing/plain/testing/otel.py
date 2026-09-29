"""
Capture the OpenTelemetry spans and metrics emitted during a block.

The global tracer/meter providers are install-once per process, so the two
install helpers are idempotent — repeated calls return the same source, and
every capture reads from that one.

The OpenTelemetry SDK imports are deferred into the install helpers so that
importing `plain.testing` (e.g. for `Client`) doesn't pay the SDK import cost.
"""

from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

from .captured import Captured, CaptureSource

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics.export import (
        DataPointT,
        HistogramDataPoint,
        Metric,
        NumberDataPoint,
    )
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
    from opentelemetry.sdk.trace.export import SpanExportResult
    from opentelemetry.trace import SpanKind
    from opentelemetry.util.types import AttributeValue

__all__ = ["CapturedMetrics", "CapturedSpans", "capture_metrics", "capture_spans"]

# Where every capture of each kind reads from. Made the first time one is
# asked for, along with the provider that feeds it.
_span_source: CaptureSource[ReadableSpan] | None = None
_metric_source: CaptureSource[Metric] | None = None

# The tracer provider installed here, for capturing. The process has one
# global provider and it can be set once, so whoever needs one for capturing
# gets it from `tracer_provider_for_capturing()`.
_tracer_provider_for_capturing: TracerProvider | None = None


def tracer_provider_for_capturing() -> TracerProvider:
    """
    The process's tracer provider, as long as it is one installed here.

    Installs it the first time it's asked for, when nothing has installed
    one, and returns the same provider after that. It starts with no span
    processors: it records nothing until a capture adds its own.

    Raises when the provider in place was installed by something else.
    `set_tracer_provider` is one-shot, so a second one would be ignored
    without a word, every capture would come up empty, and what the tests
    do would be exported to wherever that provider sends it.
    """
    global _tracer_provider_for_capturing

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    if _tracer_provider_for_capturing is None:
        if not isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
            raise RuntimeError(
                "A global tracer provider is already installed, and not by"
                " plain.testing, so spans can't be captured: whatever installed"
                " it has to leave it out of a test run. (plain.connect does."
                " It reads PLAIN_TEST_RUNNING, which `plain test` sets.)"
            )
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        _tracer_provider_for_capturing = provider

    return _tracer_provider_for_capturing


def _install_test_tracer() -> CaptureSource[ReadableSpan]:
    global _span_source
    if _span_source is None:
        from opentelemetry.sdk.trace.export import (
            SimpleSpanProcessor,
            SpanExportResult,
        )
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        class SpanExporterForCaptures(InMemorySpanExporter):
            """
            Keeps the spans that end while a capture is open. Once installed,
            the provider hands this every span for the rest of the run, and
            the ones nobody is capturing would otherwise be kept until the
            next capture emptied them.
            """

            def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
                if not source.capturing:
                    return SpanExportResult.SUCCESS
                return super().export(spans)

        exporter = SpanExporterForCaptures()
        source = CaptureSource(read=exporter.get_finished_spans, clear=exporter.clear)

        # Raises when the provider in place isn't ours to add to.
        provider = tracer_provider_for_capturing()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        _span_source = source
    return _span_source


def _install_test_meter() -> CaptureSource[Metric]:
    global _metric_source
    if _metric_source is None:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import (
            Counter,
            Histogram,
            MeterProvider,
            UpDownCounter,
        )
        from opentelemetry.sdk.metrics.export import (
            AggregationTemporality,
            InMemoryMetricReader,
        )

        # Delta temporality so each collection only reports what happened
        # since the last one — that's what makes the drain-on-entry in
        # capture_metrics() actually isolate one test's metrics from the
        # counters accumulated by everything that ran before it.
        reader = InMemoryMetricReader(
            preferred_temporality={
                Counter: AggregationTemporality.DELTA,
                UpDownCounter: AggregationTemporality.DELTA,
                Histogram: AggregationTemporality.DELTA,
            }
        )
        provider = MeterProvider(metric_readers=[reader])
        metrics.set_meter_provider(provider)
        if metrics.get_meter_provider() is not provider:
            raise RuntimeError(
                "A global meter provider is already installed, and not by"
                " plain.testing, so metrics can't be captured: whatever"
                " installed it has to leave it out of a test run."
                " (plain.connect does. It reads PLAIN_TEST_RUNNING, which"
                " `plain test` sets.)"
            )

        # The reader hands over what was recorded since it was last asked,
        # and then no longer has it. So what it hands over is kept here, for
        # every open capture to read.
        collected: list[Metric] = []

        def collect() -> list[Metric]:
            """Collect what the reader holds — which also asks every
            observable instrument for its current value — and keep it."""
            data = reader.get_metrics_data()
            if data is not None:
                for resource_metrics in data.resource_metrics:
                    for scope_metrics in resource_metrics.scope_metrics:
                        collected.extend(scope_metrics.metrics)
            return collected

        _metric_source = CaptureSource(read=collect, clear=collected.clear)
    return _metric_source


class CapturedSpans(Captured["ReadableSpan"]):
    """
    The spans that ended during a `capture_spans` block, in the order they
    ended. Each one is OpenTelemetry's own `ReadableSpan`.
    """

    def __init__(self) -> None:
        super().__init__(helper="capture_spans")

    def filter(
        self, *, name: str | None = None, kind: SpanKind | None = None
    ) -> list[ReadableSpan]:
        """
        The spans with this name, of this kind, or both.

            [span] = spans.filter(name="claim job")
            server_spans = spans.filter(kind=SpanKind.SERVER)
        """
        if name is None and kind is None:
            raise TypeError("filter() needs a name=, a kind=, or both")
        return [
            span
            for span in self
            if (name is None or span.name == name)
            and (kind is None or span.kind == kind)
        ]


class CapturedMetrics(Captured["Metric"]):
    """
    The metrics collected for a `capture_metrics` block, in the order they
    were collected. Each one is OpenTelemetry's own `Metric`.

    What a test usually wants are a metric's data points, and those come in
    two kinds: `number_points(name)` for a counter or a gauge, and
    `histogram_points(name)` for a histogram.
    """

    def __init__(self) -> None:
        super().__init__(helper="capture_metrics")

    def number_points(
        self, name: str, *, attributes: Mapping[str, AttributeValue] | None = None
    ) -> list[NumberDataPoint]:
        """
        The data points of the counter, up-down counter or gauge with this
        name. Each has a `value`.

            points = metrics.number_points(
                "messaging.client.consumed.messages",
                attributes={"plain.jobs.outcome": "lost"},
            )
            assert sum(point.value for point in points) == 1

        Pass `attributes` to keep only the points that carry all of them.
        """
        from opentelemetry.sdk.metrics.export import NumberDataPoint

        points = self._points(name, attributes)
        for point in points:
            if not isinstance(point, NumberDataPoint):
                raise TypeError(
                    f"{name!r} is a histogram — read it with"
                    f" `histogram_points({name!r})`."
                )
        return cast("list[NumberDataPoint]", points)

    def histogram_points(
        self, name: str, *, attributes: Mapping[str, AttributeValue] | None = None
    ) -> list[HistogramDataPoint]:
        """
        The data points of the histogram with this name. Each has a `count`,
        a `sum`, a `min` and a `max`.

            points = metrics.histogram_points(
                "db.client.response.returned_rows",
                attributes={"db.operation.name": "SELECT"},
            )
            assert sum(point.sum for point in points) == 5

        Pass `attributes` to keep only the points that carry all of them.
        """
        from opentelemetry.sdk.metrics.export import HistogramDataPoint

        points = self._points(name, attributes)
        for point in points:
            if not isinstance(point, HistogramDataPoint):
                raise TypeError(
                    f"{name!r} is not a histogram — read it with"
                    f" `number_points({name!r})`."
                )
        return cast("list[HistogramDataPoint]", points)

    def _points(
        self, name: str, attributes: Mapping[str, AttributeValue] | None
    ) -> list[DataPointT]:
        wanted = attributes or {}
        points = []
        for metric in self:
            if metric.name != name:
                continue
            for point in metric.data.data_points:
                carried = point.attributes or {}
                if all(
                    key in carried and carried[key] == value
                    for key, value in wanted.items()
                ):
                    points.append(point)
        return points


@contextmanager
def capture_spans() -> Generator[CapturedSpans]:
    """
    The OpenTelemetry spans that end during the block.

        with capture_spans() as spans:
            Client().get("/")

        [server_span] = spans.filter(kind=SpanKind.SERVER)
    """
    source = _install_test_tracer()
    captured = CapturedSpans()
    with source.capturing_into(captured):
        yield captured


@contextmanager
def capture_metrics() -> Generator[CapturedMetrics]:
    """
    The OpenTelemetry metrics recorded during the block.

        with capture_metrics() as metrics:
            Client().get("/")

        assert metrics.histogram_points("http.server.request.duration")

    Metrics are collected when the block ends, which is also when an
    observable instrument (a gauge that reports a pool's size, say) is asked
    for its value. So whatever it observes has to still be there: open the
    capture inside the block that keeps it alive, not around it.
    """
    source = _install_test_meter()
    captured = CapturedMetrics()
    # What was recorded before the block is collected as the capture starts,
    # so it lands before the point this capture reads from.
    with source.capturing_into(captured):
        yield captured
