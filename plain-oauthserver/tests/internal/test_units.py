"""Unit tests for the pieces below the HTTP contract."""

from app.users.models import User
from oauth_helpers import generate_pkce_pair
from plain.oauthserver.models import (
    AuthorizationCode,
    OAuthApplication,
    _hash_token,
)
from plain.utils import timezone


def unsaved_code(*, code_challenge: str) -> AuthorizationCode:
    """An in-memory AuthorizationCode for exercising its pure methods.

    The typed constructor requires every non-defaulted field, so the relation
    and expiry values are filler — `verify_code_challenge` reads none of them.
    """
    return AuthorizationCode(
        application=OAuthApplication(redirect_uris="https://app.example.com/cb"),
        user=User(email="pkce@example.com"),
        redirect_uri="https://app.example.com/cb",
        expires_at=timezone.now(),
        code_challenge=code_challenge,
    )


# PKCE
def test_pkce_s256_match():
    verifier, challenge = generate_pkce_pair()
    code = unsaved_code(code_challenge=challenge)
    assert code.verify_code_challenge(verifier) is True


def test_pkce_s256_mismatch():
    _, challenge = generate_pkce_pair()
    code = unsaved_code(code_challenge=challenge)
    assert code.verify_code_challenge("wrong") is False


def test_pkce_non_s256_challenge_rejected():
    # Verification is always S256, so a plain-style challenge (the challenge
    # equal to the verifier) can't match — PKCE downgrade is impossible.
    code = unsaved_code(code_challenge="abc")
    assert code.verify_code_challenge("abc") is False


# Redirect matching
def test_redirect_exact_match():
    app = OAuthApplication(redirect_uris="https://app.example.com/cb")
    assert app.is_valid_redirect_uri("https://app.example.com/cb")
    assert not app.is_valid_redirect_uri("https://app.example.com/other")


def test_redirect_loopback_ignores_port():
    # RFC 8252: a CLI's loopback port is unknowable at registration time.
    app = OAuthApplication(redirect_uris="http://127.0.0.1/callback")
    assert app.is_valid_redirect_uri("http://127.0.0.1:53219/callback")
    assert app.is_valid_redirect_uri("http://127.0.0.1/callback")


def test_redirect_loopback_does_not_match_different_path():
    app = OAuthApplication(redirect_uris="http://localhost/callback")
    assert not app.is_valid_redirect_uri("http://localhost:5000/evil")


# Token hashing
def test_token_hash_is_stable_and_not_plaintext():
    assert _hash_token("abc") == _hash_token("abc")
    assert _hash_token("abc") != "abc"
    assert len(_hash_token("abc")) == 64  # sha256 hex
