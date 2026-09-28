import gc
import weakref
from contextlib import contextmanager

from plain.test import TestLifecycle, patch, raises, skip, skip_test
from plain.test.runner import execution
from plain.test.runner.collection import RunnableTest
from plain.test.runner.execution import run_tests


def make_test(func, id="test_x.py::test_x", tags=(), skip_reason=None):
    return RunnableTest(id=id, func=func, tags=tags, skip_reason=skip_reason)


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


def test_skip_test_reports_the_test_skipped_with_its_reason():
    ran = []

    def skips_partway():
        ran.append("before")
        skip_test("no bucket reachable")
        ran.append("after")

    run = run_tests([make_test(skips_partway)], lifecycles=[])
    assert [r.outcome for r in run.results] == ["skipped"]
    assert run.results[0].skip_reason == "no bucket reachable"
    assert ran == ["before"]
    assert run.ok


def test_skip_decorator_reason_is_on_the_result():
    run = run_tests([make_test(lambda: None, skip_reason="not yet")], lifecycles=[])
    assert run.results[0].skip_reason == "not yet"


def test_skip_test_still_exits_the_lifecycles():
    log = []
    a = RecordingLifecycle("a", log)

    def skips():
        log.append("test")
        skip_test("not here")

    run = run_tests([make_test(skips)], lifecycles=[a])
    assert run.results[0].outcome == "skipped"
    assert log == ["setup:a", "enter:a", "test", "exit:a", "teardown:a"]


def test_skip_test_works_in_an_async_test():
    async def skips():
        skip_test("async and skipped")

    run = run_tests([make_test(skips)], lifecycles=[])
    assert run.results[0].outcome == "skipped"
    assert run.results[0].skip_reason == "async and skipped"


def test_skip_test_is_not_swallowed_by_except_exception():
    ran = []

    def catches_everything_ordinary():
        try:
            skip_test("skipped inside a try")
        except Exception:
            ran.append("swallowed")
        ran.append("carried on")

    run = run_tests([make_test(catches_everything_ordinary)], lifecycles=[])
    assert run.results[0].outcome == "skipped"
    assert ran == []


def test_skip_test_requires_a_reason():
    with raises(TypeError, match="requires a reason"):
        skip_test("")
    with raises(TypeError, match="requires a reason"):
        skip_test("   ")


def test_a_failing_lifecycle_exit_outranks_the_skip():
    class FailsOnExit(TestLifecycle):
        @contextmanager
        def around_test(self, test):
            try:
                yield
            finally:
                raise RuntimeError("could not clean up")

    def skips():
        skip_test("skipped, but the cleanup breaks")

    run = run_tests([make_test(skips)], lifecycles=[FailsOnExit()])
    assert run.results[0].outcome == "failed"


@skip("proves @skip works when collected by the engine itself")
def test_skip_decorator_is_honored():
    raise AssertionError("never runs")


# What a failure carries


def test_a_failure_carries_text_and_lets_go_of_everything_else():
    class Order:
        pass

    watching = []

    def failing():
        order = Order()
        watching.append(weakref.ref(order))
        raise ValueError("no total")

    run = run_tests([make_test(failing)], lifecycles=[])

    (result,) = run.results
    assert result.failure is not None
    assert result.failure.error_type == "ValueError"
    assert result.failure.error_message == "no total"
    assert "ValueError: no total" in result.failure.traceback
    assert result.failure.rerun_command == "plain test test_x.py::test_x"
    gc.collect()
    assert watching[0]() is None


def test_a_failure_is_described_while_the_lifecycles_are_in_place():
    in_place = []

    class Protecting(TestLifecycle):
        @contextmanager
        def around_test(self, test):
            in_place.append("entered")
            try:
                yield
            finally:
                in_place.append("exited")

        def describe_value(self, value):
            in_place.append(f"described {value!r}")

    def failing():
        total = 41
        raise ValueError(total)

    failing_test = RunnableTest(id="test_x.py::test_x", func=failing, function=failing)
    run_tests([failing_test], lifecycles=[Protecting()])

    assert in_place == ["entered", "described 41", "exited"]


def test_a_failure_that_cannot_be_described_is_still_reported():
    def describing_goes_wrong(error, **kwargs):
        raise RuntimeError("the printer broke")

    def failing():
        raise ValueError("no total")

    with patch(execution, "describe_failure", describing_goes_wrong):
        run = run_tests([make_test(failing)], lifecycles=[])

    (result,) = run.results
    assert result.outcome == "failed"
    assert result.failure is not None
    assert "ValueError: no total" in result.failure.traceback
    assert "RuntimeError: the printer broke" in result.failure.traceback
