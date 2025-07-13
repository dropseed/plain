from opentelemetry.semconv.attributes import db_attributes

from plain import models


@models.register_model
class Trace(models.Model):
    trace_id = models.CharField(max_length=255)
    start_time = models.DateTimeField(allow_null=True, required=False)
    end_time = models.DateTimeField(allow_null=True, required=False)

    description = models.TextField(default="", required=False)

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

    def __str__(self):
        return self.trace_id

    def duration_ms(self):
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None


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

    def __str__(self):
        return self.span_id

    def duration_ms(self):
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None

    def description(self):
        if summary := self.attributes.get(db_attributes.DB_QUERY_SUMMARY):
            return summary
        if query := self.attributes.get(db_attributes.DB_QUERY_TEXT):
            return query
        return self.name
