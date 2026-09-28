from plain.passwords.types import PasswordField
from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    password: Field[str] = PasswordField()

    def __str__(self) -> str:
        return self.email
