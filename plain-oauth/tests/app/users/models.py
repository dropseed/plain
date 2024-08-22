from plain import models


class User(models.Model):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.username