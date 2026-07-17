from contextlib import contextmanager

from plain.test import TestLifecycle, skip
from plain.testing.collection import CollectedTest
from plain.testing.runner import run_tests


def make_test(func, id="test_x.py::test_x", tags=(), skip_reason=None):
    return CollectedTest(id=id, func=func, tags=tags, skip_reason=skip_reason)


class RecordingLifecycle(TestLifecycle):
    def __init__(self, name, log, fail_setup=False, fail_teardown=False):
        self.name = name
        self.log = log
        self.fail_setup = fail_setup
        self.fail_teardown = fail_teardown

    def setup_worker(self):
        if self.fail_setup:
            raise RuntimeError(f"{self.name} setup failed")
        self.log.append(f"setup:{self.name}")

    def teardown_worker(self):
        if self.fail_teardown:
            raise RuntimeError(f"{self.name} teardown failed")
        self.log.append(f"teardown:{self.name}")

    @contextmanager
    def around_test(self, test):
        self.log.append(f"enter:{self.name}")
        try:
            yield
        finally:
            self.log.append(f"exit:{self.name}")


def test_outcomes_and_fail_fast():
    ran = []

    def passes():
        ran.append("passes")

    def fails():
        raise AssertionError("nope")

    def never_runs():
        ran.append("never")

    run = run_tests(
        [
            make_test(passes, id="t.py::test_passes"),
            make_test(fails, id="t.py::test_fails"),
            make_test(never_runs, id="t.py::test_never"),
        ],
        lifecycles=[],
        fail_fast=True,
    )
    assert [r.outcome for r in run.results] == ["passed", "failed"]
    assert ran == ["passes"]
    assert not run.ok


def test_skip_reason_reported_without_running():
    def boom():
        raise AssertionError("should not run")

    run = run_tests(
        [make_test(boom, skip_reason="not yet")],
        lifecycles=[],
    )
    assert run.results[0].outcome == "skipped"
    assert run.results[0].test.skip_reason == "not yet"


def test_async_test_runs():
    async def test_async():
        assert True

    run = run_tests([make_test(test_async)], lifecycles=[])
    assert run.ok


def test_lifecycles_wrap_in_order():
    log = []
    a = RecordingLifecycle("a", log)
    b = RecordingLifecycle("b", log)

    run_tests([make_test(lambda: log.append("test"))], lifecycles=[a, b])
    assert log == [
        "setup:a",
        "setup:b",
        "enter:a",
        "enter:b",
        "test",
        "exit:b",
        "exit:a",
        "teardown:b",
        "teardown:a",
    ]


def test_setup_failure_tears_down_completed_lifecycles():
    log = []
    a = RecordingLifecycle("a", log)
    b = RecordingLifecycle("b", log, fail_setup=True)

    try:
        run_tests([make_test(lambda: None)], lifecycles=[a, b])
    except RuntimeError:
        pass
    assert log == ["setup:a", "teardown:a"]


def test_teardown_failure_does_not_skip_other_teardowns():
    log = []
    a = RecordingLifecycle("a", log)
    b = RecordingLifecycle("b", log, fail_teardown=True)

    run = run_tests([make_test(lambda: log.append("test"))], lifecycles=[a, b])
    assert run.ok
    assert "teardown:a" in log  # a's teardown ran despite b's raising


@skip("proves @skip works when collected by the engine itself")
def test_skip_decorator_is_honored():
    raise AssertionError("never runs")
