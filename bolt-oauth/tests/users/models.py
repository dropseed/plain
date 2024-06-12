from bolt.auth.models import BaseUser
from bolt.db import models


class User(BaseUser):
    # Make email unique (is isn't by default)
    email = models.EmailField(unique=True)
