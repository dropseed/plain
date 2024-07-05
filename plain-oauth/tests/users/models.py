from plain.auth.models import BaseUser
from plain.db import models


class User(BaseUser):
    # Make email unique (is isn't by default)
    email = models.EmailField(unique=True)
