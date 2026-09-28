"""
Capture the OpenTelemetry spans and metrics emitted during a block.

The global tracer/meter providers are install-once per process, so the two
install helpers are idempotent — repeated calls return the same
exporter/reader, and every capture reads from that one.

The OpenTelemetry SDK imports are deferred into the install helpers so that
importing `plain.test` (e.g. for `Client`) doesn't pay the SDK import cost.
"""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

from .captured import Captured

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics.export import (
        DataPointT,
        HistogramDataPoint,
        InMemoryMetricReader,
        Metric,
        NumberDataPoint,
    )
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    from opentelemetry.trace import SpanKind
    from opentelemetry.util.types import AttributeValue

__all__ = ["CapturedMetrics", "CapturedSpans", "capture_metrics", "capture_spans"]

_span_exporter: InMemorySpanExporter | None = None
_metric_reader: InMemoryMetricReader | None = None

# Captures can be nested (a project lifecycle around every test, and the
# test's own inside it), and they all read the one exporter and the one
# reader. So an inner capture must not empty them: each capture remembers
# where it started, and they're only emptied when nothing is capturing.
_open_span_captures = 0
_open_metric_captures = 0
_collected_metrics: list[Metric] = []


def _install_test_tracer() -> InMemorySpanExporter:
    global _span_exporter
    if _span_exporter is None:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        _span_exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
        trace.set_tracer_provider(provider)
        if trace.get_tracer_provider() is not provider:
            # set_tracer_provider is one-shot: if another provider was
            # installed first (e.g. plain.connect exporting for real), the
            # call is silently ignored and every capture would come up empty
            # — while test traffic exports to the real backend. Fail loudly.
            _span_exporter = None
            raise RuntimeError(
                "A global tracer provider is already installed — disable it "
                "for tests (e.g. PLAIN_CONNECT_EXPORT_ENABLED=false) so spans "
                "can be captured."
            )
    return _span_exporter


def _install_test_meter() -> InMemoryMetricReader:
    global _metric_reader
    if _metric_reader is None:
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
        _metric_reader = InMemoryMetricReader(
            preferred_temporality={
                Counter: AggregationTemporality.DELTA,
                UpDownCounter: AggregationTemporality.DELTA,
                Histogram: AggregationTemporality.DELTA,
            }
        )
        provider = MeterProvider(metric_readers=[_metric_reader])
        metrics.set_meter_provider(provider)
        if metrics.get_meter_provider() is not provider:
            _metric_reader = None
            raise RuntimeError(
                "A global meter provider is already installed — disable it "
                "for tests so metrics can be captured."
            )
    return _metric_reader


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
    global _open_span_captures

    exporter = _install_test_tracer()
    if _open_span_captures == 0:
        exporter.clear()
    start = len(exporter.get_finished_spans())

    captured = CapturedSpans()
    _open_span_captures += 1
    try:
        yield captured
    finally:
        _open_span_captures -= 1
        captured._finish(exporter.get_finished_spans()[start:])


def _collect_metrics(reader: InMemoryMetricReader) -> None:
    """Collect what the reader holds — which also asks every observable
    instrument for its current value — and keep it."""
    data = reader.get_metrics_data()
    if data is None:
        return
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            _collected_metrics.extend(scope_metrics.metrics)


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
    global _open_metric_captures

    reader = _install_test_meter()
    # What was recorded before the block belongs to whatever came before.
    _collect_metrics(reader)
    if _open_metric_captures == 0:
        _collected_metrics.clear()
    start = len(_collected_metrics)

    captured = CapturedMetrics()
    _open_metric_captures += 1
    try:
        yield captured
    finally:
        _open_metric_captures -= 1
        _collect_metrics(reader)
        captured._finish(_collected_metrics[start:])
