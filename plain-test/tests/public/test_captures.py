"""The shape `capture_spans`, `capture_metrics` and `capture_logs` share.

Each hands back a read-only sequence of what happened inside its block, in
order, that can be read once the block has ended.
"""

import logging
from collections.abc import Iterator

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics.export import Metric
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind
from plain.test import (
    Captured,
    capture_logs,
    capture_metrics,
    capture_spans,
    case,
    cases,
    patch,
    raises,
)

tracer = trace.get_tracer("plain.tests.captures")
meter = metrics.get_meter("plain.tests.captures")
requests_counter = meter.create_counter("plain.tests.captures.requests")
duration_histogram = meter.create_histogram("plain.tests.captures.duration")
logger = logging.getLogger("plain.tests.captures")

# The gauge below reports this value, and nothing at all while it's unset —
# an instrument can't be taken back, so it has to go quiet for the tests
# that run after this file.
observed: dict[str, int] = {}


def observe_the_value(
    options: metrics.CallbackOptions,
) -> Iterator[metrics.Observation]:
    if "value" in observed:
        yield metrics.Observation(observed["value"])


meter.create_observable_gauge(
    "plain.tests.captures.observed", callbacks=[observe_the_value]
)


def emit_span() -> None:
    with tracer.start_as_current_span("captured span"):
        pass


def emit_metric() -> None:
    requests_counter.add(1)


def emit_log() -> None:
    logger.error("Captured log")


CAPTURES = (
    case(capture_spans, emit_span, ReadableSpan, id="spans"),
    case(capture_metrics, emit_metric, Metric, id="metrics"),
    case(capture_logs, emit_log, logging.LogRecord, id="logs"),
)


@cases(*CAPTURES)
def test_a_capture_is_a_sequence_of_what_happened(capture, emit, item_type):
    with capture() as captured:
        emit()

    assert isinstance(captured, Captured)
    assert len(captured) == 1
    assert isinstance(captured[0], item_type)
    assert [type(item) for item in captured] == [type(captured[0])]
    assert captured[0] in captured
    assert captured


@cases(*CAPTURES)
def test_a_block_where_nothing_happens_captures_nothing(capture, emit, item_type):
    emit()

    with capture() as captured:
        pass

    assert not captured
    assert list(captured) == []


@cases(*CAPTURES)
def test_a_capture_equals_a_list_or_tuple_of_the_same_items(capture, emit, item_type):
    with capture() as nothing:
        pass
    with capture() as captured:
        emit()

    assert nothing == []
    assert nothing == ()
    assert captured != []
    assert captured == [captured[0]]
    assert captured == (captured[0],)
    assert captured != "a string"


@cases(*CAPTURES)
def test_reading_inside_the_block_raises(capture, emit, item_type):
    with capture() as captured:
        emit()
        with raises(RuntimeError) as caught:
            len(captured)

    message = str(caught.exception)
    assert f"{capture.__name__}() is still capturing" in message
    assert f"after the `with {capture.__name__}()` block ends" in message
    # It can be read now that the block has ended.
    assert len(captured) == 1


@cases(*CAPTURES)
def test_a_capture_shows_whether_it_is_finished(capture, emit, item_type):
    with capture() as captured:
        assert "still capturing" in repr(captured)

    assert "still capturing" not in repr(captured)


@cases(*CAPTURES)
def test_a_capture_cannot_be_changed(capture, emit, item_type):
    with capture() as captured:
        emit()

    with raises(TypeError):
        captured[0] = None
    with raises(AttributeError):
        captured.append(None)


@cases(*CAPTURES)
def test_a_block_that_raises_still_has_what_it_captured(capture, emit, item_type):
    with raises(ZeroDivisionError), capture() as captured:
        emit()
        1 / 0  # noqa: B018

    assert len(captured) == 1


@cases(*CAPTURES)
def test_what_happens_after_the_block_is_not_captured(capture, emit, item_type):
    with capture() as captured:
        emit()

    emit()

    assert len(captured) == 1


@cases(*CAPTURES)
def test_an_earlier_capture_keeps_what_it_captured(capture, emit, item_type):
    with capture() as first:
        emit()

    with capture() as second:
        emit()
        emit()

    assert len(first) == 1
    if capture is capture_metrics:
        # Two additions to one counter are one data point.
        assert second.number_points("plain.tests.captures.requests")[0].value == 2
    else:
        assert len(second) == 2


@cases(*CAPTURES)
def test_a_capture_inside_another_leaves_the_outer_one_whole(capture, emit, item_type):
    with capture() as outer:
        emit()
        with capture() as inner:
            emit()
        emit()

    assert len(inner) == 1
    if capture is capture_metrics:
        # The counter was collected when the inner block started, when it
        # ended, and when the outer one ended.
        points = outer.number_points("plain.tests.captures.requests")
        assert [point.value for point in points] == [1, 1, 1]
    else:
        assert len(outer) == 3


def test_spans_filter_by_name_and_kind():
    with capture_spans() as spans:
        with tracer.start_as_current_span("fetch", kind=SpanKind.CLIENT):
            pass
        with tracer.start_as_current_span("fetch", kind=SpanKind.SERVER):
            pass
        with tracer.start_as_current_span("store", kind=SpanKind.CLIENT):
            pass

    assert [span.kind for span in spans.filter(name="fetch")] == [
        SpanKind.CLIENT,
        SpanKind.SERVER,
    ]
    assert [span.name for span in spans.filter(kind=SpanKind.CLIENT)] == [
        "fetch",
        "store",
    ]
    [span] = spans.filter(name="fetch", kind=SpanKind.SERVER)
    assert span.name == "fetch"
    assert spans.filter(name="nothing by this name") == []


def test_spans_filter_needs_something_to_filter_by():
    with capture_spans() as spans:
        emit_span()

    with raises(TypeError, match="needs a name=, a kind=, or both"):
        spans.filter()


def test_number_points_are_the_points_of_a_counter():
    with capture_metrics() as captured:
        requests_counter.add(2, {"route": "/"})
        requests_counter.add(3, {"route": "/about"})

    points = captured.number_points("plain.tests.captures.requests")
    assert sorted(point.value for point in points) == [2, 3]

    [about] = captured.number_points(
        "plain.tests.captures.requests", attributes={"route": "/about"}
    )
    assert about.value == 3
    assert (
        captured.number_points(
            "plain.tests.captures.requests", attributes={"route": "/missing"}
        )
        == []
    )
    assert captured.number_points("no metric by this name") == []


def test_histogram_points_are_the_points_of_a_histogram():
    with capture_metrics() as captured:
        duration_histogram.record(0.25, {"route": "/"})
        duration_histogram.record(0.75, {"route": "/"})

    [point] = captured.histogram_points(
        "plain.tests.captures.duration", attributes={"route": "/"}
    )
    assert point.count == 2
    assert point.sum == 1.0
    assert point.min == 0.25
    assert point.max == 0.75


def test_asking_for_the_wrong_kind_of_point_says_which_to_use():
    with capture_metrics() as captured:
        requests_counter.add(1)
        duration_histogram.record(0.5)

    with raises(TypeError, match="is a histogram — read it with `histogram_points"):
        captured.number_points("plain.tests.captures.duration")
    with raises(TypeError, match="is not a histogram — read it with `number_points"):
        captured.histogram_points("plain.tests.captures.requests")


def test_an_observable_gauge_is_read_when_the_block_ends():
    with patch(observed, "value", 10), capture_metrics() as captured:
        observed["value"] = 20

    [point] = captured.number_points("plain.tests.captures.observed")
    assert point.value == 20
