"""Behavior regression baseline — plain.passwords authentication views.

Drives login / signup / forgot-password / reset-via-token / change-password
end-to-end through ``plain.test.Client``. Assertions cover only what a browser
observes — HTTP status, redirect targets, login state (probed via the
login-gated ``/whoami`` view), database rows, and sent email.
"""

from __future__ import annotations

import re

from app.users.models import User

from plain.email.test import outbox
from plain.test import Client

# Passwords chosen to satisfy PasswordField's default validators
# (minimum length, not a common password, not entirely numeric).
OLD_PASSWORD = "sunflower-old-1"
NEW_PASSWORD = "moonlight-new-2"
WRONG_PASSWORD = "incorrect-pw-9"


def make_user(email: str = "person@example.com", password: str = OLD_PASSWORD) -> User:
    return User.query.create(email=email, password=password)


def is_logged_in(client: Client) -> bool:
    """Whether the client's current session authenticates the /whoami view."""
    return client.get("/whoami").status_code == 200


def password_works(email: str, password: str) -> bool:
    """Whether a fresh login with these credentials is accepted."""
    response = Client().post("/login", form_data={"email": email, "password": password})
    return response.status_code == 302


class TestLogin:
    def test_login_page_renders(self):
        response = Client().get("/login")

        assert response.status_code == 200
        assert 'name="email"' in response.content.decode()

    def test_valid_credentials_log_in_and_redirect(self):
        make_user(email="login-ok@example.com")
        client = Client()

        response = client.post(
            "/login",
            form_data={"email": "login-ok@example.com", "password": OLD_PASSWORD},
        )

        assert response.status_code == 302
        assert response.url == "/done"
        assert is_logged_in(client)

    def test_wrong_password_is_rejected(self):
        make_user(email="login-bad@example.com")
        client = Client()

        response = client.post(
            "/login",
            form_data={"email": "login-bad@example.com", "password": WRONG_PASSWORD},
        )

        assert response.status_code == 200
        assert "form-error" in response.content.decode()
        assert not is_logged_in(client)

    def test_unknown_email_is_rejected(self):
        client = Client()

        response = client.post(
            "/login",
            form_data={"email": "nobody@example.com", "password": OLD_PASSWORD},
        )

        assert response.status_code == 200
        assert "form-error" in response.content.decode()
        assert not is_logged_in(client)


class TestSignup:
    def test_valid_signup_creates_user_and_redirects(self):
        client = Client()

        response = client.post(
            "/signup",
            form_data={
                "email": "new@example.com",
                "password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
        )

        assert response.status_code == 302
        assert User.query.filter(email="new@example.com").exists()

    def test_password_mismatch_creates_no_user(self):
        client = Client()

        response = client.post(
            "/signup",
            form_data={
                "email": "mismatch@example.com",
                "password": NEW_PASSWORD,
                "confirm_password": WRONG_PASSWORD,
            },
        )

        assert response.status_code == 200
        assert "form-error" in response.content.decode()
        assert not User.query.filter(email="mismatch@example.com").exists()


class TestForgotPassword:
    def test_known_email_sends_reset_email(self):
        make_user(email="known@example.com")
        client = Client()

        response = client.post("/forgot", form_data={"email": "known@example.com"})

        assert response.status_code == 302
        assert response.url == "/done"
        assert len(outbox) == 1
        assert outbox[0].to == ["known@example.com"]

    def test_unknown_email_sends_nothing_without_leaking(self):
        client = Client()

        response = client.post("/forgot", form_data={"email": "ghost@example.com"})

        # Identical 302 -> /done as the known-email case: no existence leak.
        assert response.status_code == 302
        assert response.url == "/done"
        assert len(outbox) == 0


class TestResetPassword:
    def test_valid_token_sets_new_password(self):
        make_user(email="reset@example.com", password=OLD_PASSWORD)

        # Request the reset email and follow the tokened link it carries.
        client = Client()
        client.post("/forgot", form_data={"email": "reset@example.com"})
        assert len(outbox) == 1
        match = re.search(r"/reset\?token=[^\s\"'<>]+", outbox[0].body)
        assert match, "reset email should contain a tokened /reset link"
        assert client.get(match.group(0), follow_redirects=True).status_code == 200

        response = client.post(
            "/reset",
            form_data={"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        )

        assert response.status_code == 302
        assert password_works("reset@example.com", NEW_PASSWORD)
        assert not password_works("reset@example.com", OLD_PASSWORD)

    def test_invalid_token_is_rejected(self):
        client = Client()

        response = client.get("/reset?token=not-a-real-token", follow_redirects=True)

        assert response.status_code == 400
        assert not is_logged_in(client)


class TestChangePassword:
    def test_correct_old_password_changes_it(self):
        client = Client()
        client.force_login(make_user(email="change-ok@example.com"))

        response = client.post(
            "/change",
            form_data={
                "current_password": OLD_PASSWORD,
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )

        assert response.status_code == 302
        assert password_works("change-ok@example.com", NEW_PASSWORD)
        assert not password_works("change-ok@example.com", OLD_PASSWORD)

    def test_wrong_old_password_is_rejected(self):
        client = Client()
        client.force_login(make_user(email="change-bad@example.com"))

        response = client.post(
            "/change",
            form_data={
                "current_password": WRONG_PASSWORD,
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )

        assert response.status_code == 200
        assert "form-error" in response.content.decode()
        assert password_works("change-bad@example.com", OLD_PASSWORD)  # unchanged

    def test_mismatched_new_passwords_are_rejected(self):
        client = Client()
        client.force_login(make_user(email="change-mismatch@example.com"))

        response = client.post(
            "/change",
            form_data={
                "current_password": OLD_PASSWORD,
                "new_password1": NEW_PASSWORD,
                "new_password2": WRONG_PASSWORD,
            },
        )

        assert response.status_code == 200
        assert "form-error" in response.content.decode()
        assert password_works("change-mismatch@example.com", OLD_PASSWORD)  # unchanged
