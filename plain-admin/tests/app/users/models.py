from plain import models


class User(models.Model):
    username = models.CharField(max_length=255)
    is_admin = models.BooleanField(default=False)
