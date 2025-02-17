from plain import models
from plain.packages import register_model


@register_model
class User(models.Model):
    username = models.CharField(max_length=255)
    is_admin = models.BooleanField(default=False)
