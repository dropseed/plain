from plain import models


@models.register_model
class Session(models.Model):
    session_key = models.CharField(max_length=40)
    session_data = models.JSONField(default=dict, required=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(allow_null=True)

    class Meta:
        indexes = [
            models.Index(fields=["expires_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["session_key"], name="unique_session_key")
        ]

    def __str__(self):
        return self.session_key
