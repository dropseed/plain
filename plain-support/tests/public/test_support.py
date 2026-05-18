"""Behavior regression baseline — plain.support form submission.

Drives the support form end-to-end through ``plain.test.Client``. Assertions
cover only browser-observable outcomes — HTTP status, rendered page content,
the ``SupportFormEntry`` database row, and the notification email.
"""

from __future__ import annotations

from app.users.models import User

from plain.support.models import SupportFormEntry
from plain.test import Client

FORM_URL = "/support/form/default"


class TestSupportForm:
    def test_form_page_renders(self, db):
        response = Client().get(FORM_URL)

        assert response.status_code == 200
        assert 'name="message"' in response.content.decode()

    def test_valid_submission_creates_entry_and_emails(self, db, mailoutbox):
        response = Client().post(
            FORM_URL,
            data={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "message": "I need help with my account",
            },
            follow=True,
        )

        assert response.status_code == 200
        assert "has been sent" in response.content.decode().lower()

        entry = SupportFormEntry.query.get()
        assert entry.name == "Jane Doe"
        assert entry.email == "jane@example.com"
        assert entry.message == "I need help with my account"

        # The support team is notified, with the message in the email body.
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["support-team@example.com"]
        assert "I need help with my account" in mailoutbox[0].body

    def test_invalid_submission_creates_no_entry(self, db, mailoutbox):
        response = Client().post(
            FORM_URL,
            data={"name": "Jane Doe", "email": "jane@example.com", "message": ""},
        )

        assert response.status_code == 200
        assert "form-error" in response.content.decode()
        assert SupportFormEntry.query.count() == 0
        assert len(mailoutbox) == 0

    def test_submission_links_to_logged_in_user(self, db, mailoutbox):
        user = User.query.create(email="member@example.com")
        client = Client()
        client.force_login(user)

        response = client.post(
            FORM_URL,
            data={
                "name": "Member",
                "email": "member@example.com",
                "message": "A question from a signed-in user",
            },
            follow=True,
        )

        assert response.status_code == 200
        assert SupportFormEntry.query.filter(user=user).exists()
        assert len(mailoutbox) == 1
