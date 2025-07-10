from plain import models


@models.register_model
class User(models.Model):
    username = models.CharField(max_length=255)
    is_admin = models.BooleanField(default=False)
