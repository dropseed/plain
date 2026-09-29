"""`plain request` captures spans, and so does a test, in the same process.

The process has one tracer provider and it is installed once. The command
used to install a provider of its own when it ran first, and
`capture_spans()` then refused it as somebody else's: every span capture
after a test had run `plain request` in-process failed with "A global
tracer provider is already installed". In the other order both worked.

Each order gets a process of its own, since the first capture in a process
is the one that installs.
"""

import subprocess
import sys

THE_COMMANDS_CAPTURE_THEN_A_TESTS = """\
from opentelemetry import trace

from plain.dev.request.trace import capture_trace_spans
from plain.testing import capture_spans

tracer = trace.get_tracer("either-order")

with capture_trace_spans() as exporter:
    with tracer.start_as_current_span("during the command"):
        pass
print("command:", [span.name for span in exporter.get_finished_spans()])

with capture_spans() as spans:
    with tracer.start_as_current_span("during the test"):
        pass
print("test:", [span.name for span in spans])
"""

A_TESTS_CAPTURE_THEN_THE_COMMANDS = """\
from opentelemetry import trace

from plain.dev.request.trace import capture_trace_spans
from plain.testing import capture_spans

tracer = trace.get_tracer("either-order")

with capture_spans() as spans:
    with tracer.start_as_current_span("during the test"):
        pass
print("test:", [span.name for span in spans])

with capture_trace_spans() as exporter:
    with tracer.start_as_current_span("during the command"):
        pass
print("command:", [span.name for span in exporter.get_finished_spans()])

with capture_spans() as spans:
    with tracer.start_as_current_span("during the test, again"):
        pass
print("test again:", [span.name for span in spans])
"""


def run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_command_captures_first_and_a_test_captures_after():
    completed = run(THE_COMMANDS_CAPTURE_THEN_A_TESTS)

    assert completed.returncode == 0
    assert completed.stdout.splitlines() == [
        "command: ['during the command']",
        "test: ['during the test']",
    ]


def test_a_test_captures_first_and_the_command_captures_after():
    completed = run(A_TESTS_CAPTURE_THEN_THE_COMMANDS)

    assert completed.returncode == 0
    assert completed.stdout.splitlines() == [
        "test: ['during the test']",
        "command: ['during the command']",
        "test again: ['during the test, again']",
    ]
