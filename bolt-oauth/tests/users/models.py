from bolt.auth.models import AbstractUser
from bolt.db import models


class User(AbstractUser):
    # Make email unique (is isn't by default)
    email = models.EmailField(unique=True)
