from __future__ import annotations

import pytest
from click.testing import CliRunner
from opentelemetry import trace

from plain.chores import Chore, register_chore
from plain.cli.core import cli
from plain.test.otel import install_test_tracer

_span_exporter = install_test_tracer()


@pytest.fixture
def _otel_clean() -> None:
    _span_exporter.clear()


@register_chore
class _SuccessChore(Chore):
    """Test chore that returns cleanly."""

    def run(self) -> str:
        return "ok"


@register_chore
class _BoomChore(Chore):
    """Test chore that always raises."""

    def run(self) -> None:
        raise RuntimeError("chore boom")


def _qualname(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _chore_span(name: str):
    spans = [s for s in _span_exporter.get_finished_spans() if s.name == name]
    assert spans, f"expected a span named {name!r}"
    return spans[-1]


@pytest.mark.usefixtures("_otel_clean")
def test_chore_emits_consumer_span_on_success() -> None:
    """Each chore execution gets a `chore {name}` CONSUMER span — the chore
    is the unit of work being consumed. CONSUMER puts it in the canonical
    error-attribution set (SERVER/CONSUMER/PRODUCER) alongside jobs."""
    name = _qualname(_SuccessChore)
    result = CliRunner().invoke(
        cli, ["chores", "run", "--name", name], prog_name="plain"
    )
    assert result.exit_code == 0

    span = _chore_span(f"chore {name}")
    assert span.kind == trace.SpanKind.CONSUMER
    assert span.status.status_code == trace.StatusCode.UNSET


@pytest.mark.usefixtures("_otel_clean")
def test_chore_records_error_on_failure() -> None:
    """A failing chore stamps the canonical failure signal (status=ERROR plus
    error.type) on its span. The chore catch-and-log keeps the runner alive
    so an exception in one chore doesn't skip the rest."""
    name = _qualname(_BoomChore)
    result = CliRunner().invoke(
        cli, ["chores", "run", "--name", name], prog_name="plain"
    )
    # `run_chores` calls sys.exit(1) when any chore fails.
    assert result.exit_code == 1

    span = _chore_span(f"chore {name}")
    assert span.status.status_code == trace.StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes["error.type"] == "RuntimeError"
    exception_events = [e for e in span.events if e.name == "exception"]
    assert exception_events
