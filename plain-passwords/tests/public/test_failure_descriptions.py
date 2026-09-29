"""What a failure report prints for a user: everything but the password."""

from app.users.models import User
from plain.postgres.test.lifecycle import PostgresTestLifecycle


def test_a_password_is_not_printed_with_the_user_it_belongs_to():
    user = User.query.create(email="a@example.com", password="a-strong-password-1")
    assert user.password.startswith("pbkdf2_")

    described = PostgresTestLifecycle().describe_value(user)

    assert described is not None
    assert "password=<withheld>" in described
    assert "email='a@example.com'" in described
    assert user.password not in described
    assert "pbkdf2_" not in described
