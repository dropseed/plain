import uuid

from plain import models
from plain.runtime import SettingsReference


@models.register_model
class SupportFormEntry(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=models.SET_NULL,
        related_name="support_form_entries",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    email = models.EmailField()
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    form_slug = models.CharField(max_length=255)
    # referrer? source? session?
    # extra_data

    class Meta:
        ordering = ["-created_at"]
