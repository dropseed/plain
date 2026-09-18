"""`capture_logs` — the contract tests for the log-capture vocabulary."""

from __future__ import annotations

import logging

from opentelemetry import trace
from plain.test import capture_logs, capture_spans, raises

tracer = trace.get_tracer("plain.tests.capture_logs")


def test_captures_records_from_the_plain_tree_by_default():
    with capture_logs() as logs:
        logging.getLogger("plain.jobs").warning("Job failed")

    assert logs.messages == ["Job failed"]
    assert logs[0].levelno == logging.WARNING
    assert len(logs) == 1


def test_captures_the_app_tree_by_default():
    with capture_logs() as logs:
        logging.getLogger("app").info("Something happened")

    assert logs.messages == ["Something happened"]


def test_named_loggers_narrow_the_capture():
    with capture_logs("plain.jobs") as logs:
        logging.getLogger("plain.jobs").warning("Kept")
        logging.getLogger("plain.request").warning("Dropped")

    assert logs.messages == ["Kept"]


def test_structured_context_lands_on_the_record():
    with capture_logs("plain.jobs") as logs:
        logging.getLogger("plain.jobs").warning("Job failed", extra={"job_id": 7})

    # `extra=` lands as a real attribute on the record; the type checker
    # can't know the name, which is the whole point of structured context.
    assert logs[0].job_id == 7  # ty: ignore[unresolved-attribute]


def test_a_record_reaching_two_captured_loggers_is_recorded_once():
    """The default names both sit above `plain.jobs` in no way, but an explicit
    overlapping pair does — one emit is still one record."""
    with capture_logs("plain", "plain.jobs") as logs:
        logging.getLogger("plain.jobs").warning("Once")

    assert logs.messages == ["Once"]


def test_level_argument_filters_lower_records():
    with capture_logs("plain.jobs", level=logging.ERROR) as logs:
        logging.getLogger("plain.jobs").warning("Too quiet")
        logging.getLogger("plain.jobs").error("Loud enough")

    assert logs.messages == ["Loud enough"]


def test_handlers_and_levels_are_restored_on_exit():
    logger = logging.getLogger("plain.jobs")
    original_level = logger.level
    original_handler_count = len(logger.handlers)

    with capture_logs("plain.jobs"):
        assert len(logger.handlers) == original_handler_count + 1

    assert len(logger.handlers) == original_handler_count
    assert logger.level == original_level


def test_records_emitted_inside_a_span_carry_its_context():
    with (
        capture_spans() as spans,
        capture_logs("plain.jobs") as logs,
        tracer.start_as_current_span("work"),
    ):
        logging.getLogger("plain.jobs").error("Inside")

    span = spans.find(name="work")
    context = logs.span_context_for("Inside")
    assert context.is_valid
    assert context.trace_id == span.context.trace_id
    assert context.span_id == span.context.span_id


def test_records_emitted_outside_a_span_have_an_invalid_context():
    with capture_logs("plain.jobs") as logs:
        logging.getLogger("plain.jobs").error("Outside")

    assert not logs.span_context_for("Outside").is_valid


def test_span_context_for_requires_exactly_one_matching_record():
    with capture_logs("plain.jobs") as logs:
        logging.getLogger("plain.jobs").error("Twice")
        logging.getLogger("plain.jobs").error("Twice")

    with raises(LookupError, match="2 log records"):
        logs.span_context_for("Twice")

    with raises(LookupError, match="No log record"):
        logs.span_context_for("Never logged")
