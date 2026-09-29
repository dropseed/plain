"""Once `capture_spans` has been used, the provider it installed is there for
the rest of the run and is handed every span. What nobody is capturing is
dropped, not kept until the next capture."""

from opentelemetry import trace
from plain.testing import capture_spans
from plain.testing.otel import _install_test_tracer

tracer = trace.get_tracer("plain.tests.captures_keep_nothing")


def emit_span() -> None:
    with tracer.start_as_current_span("not captured"):
        pass


def test_spans_that_end_outside_a_capture_are_not_kept():
    with capture_spans() as spans:
        emit_span()
    assert len(spans) == 1

    source = _install_test_tracer()
    assert source._read() == ()

    for _ in range(3):
        emit_span()

    assert source._read() == ()


def test_spans_are_kept_while_an_outer_capture_is_still_open():
    with capture_spans() as outer:
        with capture_spans():
            emit_span()
        emit_span()

    assert len(outer) == 2
