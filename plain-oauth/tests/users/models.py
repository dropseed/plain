from plain import models
from plain.auth.models import BaseUser


class User(BaseUser):
    # Make email unique (is isn't by default)
    email = models.EmailField(unique=True)
