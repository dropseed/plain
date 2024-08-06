from plain import models


class User(models.Model):
    username = models.CharField(max_length=255)
    is_staff = models.BooleanField(default=False)
