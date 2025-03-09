from plain import models


@models.register_model
class User(models.Model):
    email = models.EmailField()
    username = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["email"], name="user_unique_email"),
            models.UniqueConstraint(fields=["username"], name="user_unique_username"),
        ]

    def __str__(self):
        return self.username
