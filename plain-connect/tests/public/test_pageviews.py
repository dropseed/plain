import base64
import hashlib
import re

from app.users.models import User
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from plain.test import Client

TOKEN = "plain_pv_testtoken"
IDENTITY_KEY = "endpoint-identity-secret"


def _data_identity(content: bytes) -> str:
    """Pull the `data-identity` attribute out of the rendered <script> tag."""
    match = re.search(rb'data-identity="([^"]*)"', content)
    assert match, f"no data-identity attribute in: {content!r}"
    return match.group(1).decode()


def _decrypt(token: str, identity_key: str) -> str:
    key = hashlib.sha256(identity_key.encode()).digest()
    raw = base64.urlsafe_b64decode(token)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()


def test_tag_renders_nothing_without_a_token(db):
    # CONNECT_PAGEVIEWS_TOKEN defaults to "" — the tag stays silent.
    response = Client().get("/")
    assert response.status_code == 200
    assert b"<script" not in response.content


def test_tag_renders_the_beacon_script_when_token_is_set(db, settings):
    settings.CONNECT_PAGEVIEWS_TOKEN = TOKEN
    response = Client().get("/")
    assert response.status_code == 200
    assert f'data-token="{TOKEN}"'.encode() in response.content
    # No identity key configured, so there is nothing to attribute.
    assert _data_identity(response.content) == ""


def test_anonymous_visitor_carries_no_identity(db, settings):
    settings.CONNECT_PAGEVIEWS_TOKEN = TOKEN
    settings.CONNECT_PAGEVIEWS_IDENTITY_KEY = IDENTITY_KEY
    response = Client().get("/")
    assert response.status_code == 200
    assert _data_identity(response.content) == ""


def test_signed_in_user_identity_is_encrypted_into_the_tag(db, settings):
    # Regression test: the user is read via plain.auth, not request.user.
    # With request.user the attribute would render empty for a logged-in user.
    settings.CONNECT_PAGEVIEWS_TOKEN = TOKEN
    settings.CONNECT_PAGEVIEWS_IDENTITY_KEY = IDENTITY_KEY

    user = User.query.create(username="dave")
    client = Client()
    client.force_login(user)

    response = client.get("/")
    assert response.status_code == 200

    token = _data_identity(response.content)
    assert token, "data-identity should be populated for a signed-in user"
    # The HTML only carries the encrypted token; it decrypts back to the id.
    assert _decrypt(token, IDENTITY_KEY) == str(user.id)
