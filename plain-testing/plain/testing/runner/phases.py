"""
Where a run's time went.

A run is mostly not tests. Before the first test the app is set up, its
packages are imported, the test files are read and the database is made,
and after the last test it is dropped. One test of 20 milliseconds is a run
of more than a second, and "1 passed in 0.02s" would not say where the rest
went. So the runner keeps the time each phase took, in the order they
happen, and the report says when they came to more than the tests did.

The clock starts when `plain.runtime` was imported, which is the first thing
a `plain` command does. What came before it, the interpreter starting and
Python's own imports, a process can't time: the nearest it has is the CPU
time it had used by then, and that is what the first phase holds, and says.
"""

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from plain.runtime import CPU_SECONDS_BEFORE_PLAIN, PLAIN_IMPORTED_AT

if TYPE_CHECKING:
    from .execution import TestRun

__all__ = []

# A package whose import took this long, or a setup hook that did, gets a
# line of its own under the runtime setup phase. The rest share one. A slow
# import is the one cost an app can cut itself.
SLOW_PART_SECONDS = 0.05


@dataclass(frozen=True, kw_only=True)
class Part:
    """One thing inside a phase that is worth a line: `import app.agents`."""

    name: str
    seconds: float


@dataclass(frozen=True, kw_only=True)
class Phase:
    # "python_startup", "command", "runtime_setup", "helper_modules",
    # "lifecycles_loaded", "collection", "lifecycle_setup", "tests",
    # "lifecycle_teardown", "report", then "unaccounted".
    name: str
    seconds: float
    # "wall" for the time from the phase's start to its end. "cpu" for
    # "python_startup", which is the CPU time the process had used before
    # the clock could start.
    measured: str = "wall"
    parts: tuple[Part, ...] = ()


class RunTimeline:
    """
    Marks the end of each phase as the run reaches it, and gives the phases
    back with what the marks don't account for as a phase of its own.
    """

    def __init__(self) -> None:
        self._started_at = PLAIN_IMPORTED_AT
        self._last_mark = self._started_at
        self._phases: list[Phase] = []

    def phase_ended(self, name: str, *, parts: tuple[Part, ...] = ()) -> None:
        now = time.perf_counter()
        self._phases.append(
            Phase(name=name, seconds=now - self._last_mark, parts=parts)
        )
        self._last_mark = now

    def run_ended(self, run: TestRun) -> None:
        """
        The run's own phases, which it timed itself: setting the lifecycles
        up, the tests, and taking the lifecycles down. What the run took
        beyond those three is left for "unaccounted".
        """
        self._phases.append(
            Phase(
                name="lifecycle_setup",
                seconds=sum((part.seconds for part in run.lifecycle_setup), 0.0),
                parts=run.lifecycle_setup,
            )
        )
        self._phases.append(Phase(name="tests", seconds=run.tests_seconds))
        self._phases.append(
            Phase(
                name="lifecycle_teardown",
                seconds=sum((part.seconds for part in run.lifecycle_teardown), 0.0),
                parts=run.lifecycle_teardown,
            )
        )
        self._last_mark = time.perf_counter()

    def phases(self) -> tuple[Phase, ...]:
        """
        Every phase so far: Python starting first, and last what the marks
        don't account for, so that the wall-clock phases add up to the time
        from the first Plain import to the last mark.
        """
        elapsed = self._last_mark - self._started_at
        accounted = sum((phase.seconds for phase in self._phases), 0.0)
        return (
            Phase(
                name="python_startup",
                seconds=CPU_SECONDS_BEFORE_PLAIN,
                measured="cpu",
            ),
            *self._phases,
            Phase(name="unaccounted", seconds=max(elapsed - accounted, 0.0)),
        )


def seconds_in_all(phases: tuple[Phase, ...]) -> float:
    """The run from Python starting to the report, as near as is known."""
    return sum((phase.seconds for phase in phases), 0.0)


def seconds_outside_the_tests(phases: tuple[Phase, ...]) -> float:
    return sum((phase.seconds for phase in phases if phase.name != "tests"), 0.0)


def runtime_setup_parts() -> tuple[Part, ...]:
    """
    What `plain.runtime.setup()` spent its time on, from what it recorded:
    the setup hooks, the settings, the packages' imports, and the packages'
    `ready()` methods. A slow hook or import has a line of its own. Nothing
    when the runtime wasn't set up (library mode).
    """
    from plain.runtime import setup_timing

    if setup_timing is None:
        return ()

    return (
        *_slow_ones_and_the_rest(setup_timing.hooks, each="hook", rest="hooks"),
        Part(name="settings", seconds=setup_timing.settings),
        *_slow_ones_and_the_rest(
            setup_timing.package_imports, each="import", rest="imports"
        ),
        Part(name="ready()", seconds=setup_timing.ready),
    )


def _slow_ones_and_the_rest(
    timed: tuple[tuple[str, float], ...], *, each: str, rest: str
) -> tuple[Part, ...]:
    """
    `import app.agents` for each one that was slow, then `other imports (24)`
    for the rest together, or `imports (25)` when none was slow.
    """
    slow = [(name, seconds) for name, seconds in timed if seconds >= SLOW_PART_SECONDS]
    parts = [Part(name=f"{each} {name}", seconds=seconds) for name, seconds in slow]
    others = len(timed) - len(slow)
    if others:
        what = f"other {rest}" if slow else rest
        seconds = sum(seconds for _, seconds in timed) - sum(
            seconds for _, seconds in slow
        )
        parts.append(Part(name=f"{what} ({others})", seconds=seconds))
    return tuple(parts)
