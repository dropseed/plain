from plain import models
from plain.models import types


@models.register_model
class User(models.Model):
    email: str = types.EmailField()
    username: str = types.CharField(max_length=100)

    model_options = models.Options(
        constraints=[
            models.UniqueConstraint(fields=["email"], name="user_unique_email"),
            models.UniqueConstraint(fields=["username"], name="user_unique_username"),
        ],
    )

    def __str__(self):
        return self.username
