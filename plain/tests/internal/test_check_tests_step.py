import subprocess

from plain.cli import check as check_module
from plain.test import cases, patch, raises


def run_that_exits_with(code):
    def run(args, *, check):
        assert args == ["plain", "test"]
        return subprocess.CompletedProcess(args, code)

    return run


def test_a_project_with_no_tests_passes_the_check():
    with patch(check_module.subprocess, "run", run_that_exits_with(4)):
        check_module.check_tests()


def test_passing_tests_pass_the_check():
    with patch(check_module.subprocess, "run", run_that_exits_with(0)):
        check_module.check_tests()


@cases(1, 2, 3, 130)
def test_anything_else_the_runner_exits_with_fails_the_check(code):
    with (
        patch(check_module.subprocess, "run", run_that_exits_with(code)),
        raises(SystemExit) as caught,
    ):
        check_module.check_tests()
    assert caught.exception.code == code
