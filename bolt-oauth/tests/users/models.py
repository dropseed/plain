from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    # Make email unique (is isn't by default)
    email = models.EmailField(unique=True)
