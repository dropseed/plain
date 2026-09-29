from plain.testing.runner.phases import (
    Part,
    Phase,
    seconds_in_all,
    seconds_outside_the_tests,
)
from plain.testing.runner.reporting import phases_heading, phases_text

PHASES = (
    Phase(name="python_startup", seconds=0.04, measured="cpu"),
    Phase(name="command", seconds=0.05),
    Phase(
        name="runtime_setup",
        seconds=0.77,
        parts=(
            Part(name="hook dev-setup", seconds=0.3),
            Part(name="import app.agents", seconds=0.4),
        ),
    ),
    Phase(name="tests", seconds=0.02),
    Phase(name="unaccounted", seconds=0.01),
)


def test_the_phases_are_a_timeline_with_the_parts_under_their_phase():
    assert phases_text(PHASES) == (
        "python startup         0.04s  cpu time, before Plain was imported\n"
        "command                0.05s\n"
        "runtime setup          0.77s\n"
        "  hook dev-setup       0.30s\n"
        "  import app.agents    0.40s\n"
        "tests                  0.02s\n"
        "unaccounted            0.01s"
    )


def test_the_heading_says_how_long_the_run_was_in_all():
    assert round(seconds_in_all(PHASES), 2) == 0.89
    assert phases_heading(PHASES) == "where the 0.89s went"


def test_everything_but_the_tests_is_outside_them():
    assert round(seconds_outside_the_tests(PHASES), 2) == 0.87
