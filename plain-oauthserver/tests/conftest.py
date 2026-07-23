from __future__ import annotations

import pytest

from plain.test import Client


@pytest.fixture
def user(db):
    from app.users.models import User

    return User.query.create(email="test@example.com")


@pytest.fixture
def public_app(db):
    """A public client (no secret) — how Claude registers via DCR."""
    from plain.oauthserver.models import OAuthApplication

    return OAuthApplication.query.create(
        name="Test App",
        redirect_uris=(
            "https://claude.ai/api/mcp/auth_callback http://localhost:3000/callback"
        ),
    )


@pytest.fixture
def authenticated_client(user):
    client = Client()
    client.force_login(user)
    return client
