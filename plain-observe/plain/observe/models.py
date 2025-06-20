from plain import models


@models.register_model
class Trace(models.Model):
    trace_id = models.CharField(max_length=255)
    start_time = models.DateTimeField(allow_null=True, required=False)
    end_time = models.DateTimeField(allow_null=True, required=False)

    # Plain fields
    request_id = models.CharField(max_length=255, default="", required=False)
    session_id = models.CharField(max_length=255, default="", required=False)
    user_id = models.CharField(max_length=255, default="", required=False)

    class Meta:
        ordering = ["-start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["trace_id"],
                name="observe_unique_trace_id",
            )
        ]


@models.register_model
class Span(models.Model):
    trace = models.ForeignKey(Trace, on_delete=models.CASCADE, related_name="spans")

    span_id = models.CharField(max_length=255)

    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=50)
    parent_id = models.CharField(max_length=255, default="", required=False)
    start_time = models.DateTimeField(allow_null=True, required=False)
    end_time = models.DateTimeField(allow_null=True, required=False)
    status = models.JSONField(default=dict)
    context = models.JSONField(default=dict)
    attributes = models.JSONField(default=dict, required=False)
    events = models.JSONField(default=list, required=False)
    links = models.JSONField(default=list, required=False)
    resource = models.JSONField(default=dict, required=False)

    class Meta:
        ordering = ["-start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["trace", "span_id"],
                name="observe_unique_span_id",
            )
        ]
        indexes = [
            models.Index(fields=["trace", "span_id"]),
            models.Index(fields=["trace"]),
            models.Index(fields=["start_time"]),
        ]
