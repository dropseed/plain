"""Exercises plain.schema.Schema as a job's input validator.

The same Schema class used in views also validates job payloads — proving
the primitive is genuinely cross-package, not forms-only. We test the
validation surface directly (the run() method is a thin wrapper).
"""

from __future__ import annotations

from plain.schema import Invalid

from app.jobs import SendNotificationJob, SendNotificationPayload


def test_payload_schema_accepts_valid_input():
    result = SendNotificationPayload.validate(
        {"user_id": "42", "channel": "email", "message": "Hi"}
    )
    # Narrow via the negative — `Valid` is generic so direct
    # isinstance(_, Valid) doesn't preserve the type parameter under ty.
    # Eliminating Invalid keeps result typed as Valid[SendNotificationPayload].
    assert not isinstance(result, Invalid)
    assert result.data.user_id == 42  # coerced from string
    assert result.data.channel == "email"
    assert result.data.message == "Hi"


def test_payload_schema_rejects_bad_choice_and_constraints():
    result = SendNotificationPayload.validate(
        {"user_id": "0", "channel": "smoke-signal", "message": ""}
    )
    assert isinstance(result, Invalid)
    assert "user_id" in result.errors  # min_value=1 violated
    assert "channel" in result.errors  # not in choices
    assert "message" in result.errors  # min_length=1 violated


def test_payload_schema_rejects_empty_payload():
    result = SendNotificationPayload.validate({})
    assert isinstance(result, Invalid)
    assert set(result.errors) == {"user_id", "channel", "message"}


def test_job_run_does_not_raise_on_invalid_payload():
    """Job swallows invalid input by logging and returning — bad payloads
    don't crash workers, they just log structured errors."""
    SendNotificationJob(payload={}).run()  # must not raise


def test_job_run_does_not_raise_on_valid_payload():
    SendNotificationJob(
        payload={"user_id": "1", "channel": "push", "message": "ok"}
    ).run()  # must not raise
