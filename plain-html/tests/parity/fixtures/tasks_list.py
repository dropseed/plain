"""Shared context for the tasks_list fixture.

Three scenarios so the renderers exercise:
- `:if`-true and `:if`-false branches
- Iteration with and without nested iteration
- Empty-collection rendering
- HTML escaping of user-provided values
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Owner:
    id: int
    name: str


@dataclass
class Alert:
    severity: str
    title: str
    body: str


@dataclass
class Task:
    id: int
    title: str
    due: str
    done: bool
    tags: list[str]


def populated() -> dict:
    tasks = [
        Task(
            id=1,
            title="Ship plain.html tracer bullet",
            due="2026-05-12",
            done=True,
            tags=["framework", "<spec>"],
        ),
        Task(
            id=2,
            title="Wire parity harness",
            due="2026-05-13",
            done=False,
            tags=["tests"],
        ),
        Task(id=3, title='Audit "render path"', due="2026-05-14", done=False, tags=[]),
    ]
    return {
        "owner": Owner(id=42, name="Dave & Co"),
        "tasks": tasks,
        "done_count": sum(1 for t in tasks if t.done),
        "alert": Alert(
            severity="info",
            title="Migration in progress",
            body='Templates marked "done" run under the new engine.',
        ),
    }


def empty() -> dict:
    return {
        "owner": Owner(id=42, name="Dave & Co"),
        "tasks": [],
        "done_count": 0,
        "alert": None,
    }


SCENARIOS = {"populated": populated, "empty": empty}
