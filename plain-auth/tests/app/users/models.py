from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class User(postgres.Model):
    username: Field[str] = types.TextField(max_length=255)
    is_admin: Field[bool] = types.BooleanField(default=False)
