"""A test run exports nothing, with nothing to configure.

plain.connect installs its exporting providers while the app is set up, and
they can't be taken out again. With an export token in the environment, as a
developer's `.env` has, a test run used to install them: what the tests did
was sent to the real backend, and `capture_spans()` refused to run.
"""

import os
import subprocess
import sys
from pathlib import Path

TESTS_DIRECTORY = Path(__file__).parent.parent

SET_UP_AND_REPORT = """\
import plain.runtime

plain.runtime.setup()

from opentelemetry import _logs, metrics, trace

print(type(trace.get_tracer_provider()).__name__)
print(type(metrics.get_meter_provider()).__name__)
print(type(_logs.get_logger_provider()).__name__)
"""


def providers_after_setup(*, in_a_test_run: bool) -> list[str]:
    environment = {
        **os.environ,
        "PLAIN_CONNECT_EXPORT_ENABLED": "true",
        "PLAIN_CONNECT_EXPORT_TOKEN": "a-token-for-the-test",
        # Nothing listens here, so a provider that does get installed
        # reaches nobody.
        "PLAIN_CONNECT_EXPORT_URL": "http://127.0.0.1:9",
    }
    if in_a_test_run:
        environment["PLAIN_TEST_RUNNING"] = "1"
    else:
        del environment["PLAIN_TEST_RUNNING"]

    completed = subprocess.run(
        [sys.executable, "-c", SET_UP_AND_REPORT],
        cwd=TESTS_DIRECTORY,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.splitlines()


def test_a_test_run_installs_no_exporting_provider():
    providers = providers_after_setup(in_a_test_run=True)

    assert providers == [
        "ProxyTracerProvider",
        "_ProxyMeterProvider",
        "ProxyLoggerProvider",
    ]


def test_outside_a_test_run_the_same_settings_install_them():
    providers = providers_after_setup(in_a_test_run=False)

    assert providers == ["TracerProvider", "MeterProvider", "LoggerProvider"]


def test_spans_can_be_captured_with_an_export_token_set():
    script = (
        SET_UP_AND_REPORT
        + """
from plain.testing import capture_spans

with capture_spans() as spans:
    with trace.get_tracer("under-test").start_as_current_span("captured"):
        pass
print([span.name for span in spans])
"""
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=TESTS_DIRECTORY,
        env={
            **os.environ,
            "PLAIN_TEST_RUNNING": "1",
            "PLAIN_CONNECT_EXPORT_ENABLED": "true",
            "PLAIN_CONNECT_EXPORT_TOKEN": "a-token-for-the-test",
            "PLAIN_CONNECT_EXPORT_URL": "http://127.0.0.1:9",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.splitlines()[-1] == "['captured']"
