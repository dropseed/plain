"""Constructing a job keeps its own type.

Checker input, not pytest input — see plain-postgres/tests/typing/README.md
for how the markers assert.
"""

from typing import assert_type

from plain.jobs import Job


class SendReport(Job):
    def __init__(self, recipient: str) -> None:
        self.recipient = recipient

    def run(self) -> None:
        pass

    def subject(self) -> str:
        return f"Report for {self.recipient}"


def constructing_a_job_keeps_the_subclass() -> None:
    job = SendReport("dave@example.com")
    assert_type(job, SendReport)
    assert_type(job.subject(), str)


def constructor_arguments_are_checked() -> None:
    SendReport(recipient=1)  # ty: ignore[invalid-argument-type]
    SendReport(bogus="x")  # ty: ignore[missing-argument, unknown-argument]
