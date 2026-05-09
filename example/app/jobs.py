import time
from typing import Any

from plain.jobs import Job, register_job
from plain.logs import app_logger
from plain.schema import Invalid, Schema, types


@register_job
class ExampleJob(Job):
    def run(self) -> None:
        app_logger.info("Example job running", context={"job": "ExampleJob"})
        time.sleep(1)
        app_logger.info("Example job finished", context={"job": "ExampleJob"})


class SendNotificationPayload(Schema):
    """Payload schema for SendNotificationJob.

    The same Schema primitive used for view input validation also works for
    job payloads — no plain.jobs changes required. validate() takes any
    dict-like, so a job that accepts a webhook-shaped payload can validate
    inside run() exactly the same way an APIView does.
    """

    user_id: int = types.IntegerField(min_value=1)
    channel: str = types.ChoiceField(
        choices=[("email", "Email"), ("sms", "SMS"), ("push", "Push")]
    )
    message: str = types.TextField(max_length=200, min_length=1)


@register_job
class SendNotificationJob(Job):
    """Demonstrates Schema inside run() — same validate()/Valid/Invalid
    machinery used in views. The payload is plain JSON-friendly data, so
    JobParameters serialization works unchanged.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def run(self) -> None:
        result = SendNotificationPayload.validate(self.payload)
        if isinstance(result, Invalid):
            app_logger.error(
                "SendNotificationJob: invalid payload",
                context={"errors": result.errors},
            )
            return

        # `result` IS the typed SendNotificationPayload instance.
        app_logger.info(
            "SendNotificationJob: dispatched",
            context={
                "user_id": result.user_id,
                "channel": result.channel,
                "message_len": len(result.message),
            },
        )
