from plain import postgres
from plain.postgres import types


@postgres.register_model
class User(postgres.Model):
    username: str = types.TextField(max_length=255)
    is_admin: bool = types.BooleanField(default=False)
