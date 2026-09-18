from plain.postgres import types

from plain import postgres


@postgres.register_model
class User(postgres.Model):
    username = types.TextField(max_length=255)
    is_admin = types.BooleanField(default=False)
