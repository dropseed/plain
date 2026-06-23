from __future__ import annotations

from plain.http.cookie import sign_cookie_value, unsign_cookie_value


def test_sign_unsign_round_trip():
    """A value signed under a (key, salt) pair unsigns back to itself."""
    signed = sign_cookie_value(key="name", value="hello", salt="extra")
    assert signed != "hello"

    out = unsign_cookie_value(
        key="name", signed_value=signed, salt="extra", default="REJECTED"
    )
    assert out == "hello"


def test_salt_namespace_collision_is_rejected():
    """
    Distinct (key, salt) pairs must not collide.

    With a non-injective ``key + salt`` signer salt, ("ab", "c") and
    ("a", "bc") both produce "abc", so a value signed in one context
    unsigns successfully in the other. The injective encoding closes that.
    """
    signed = sign_cookie_value(key="ab", value="attacker-controlled", salt="c")

    out = unsign_cookie_value(
        key="a", signed_value=signed, salt="bc", default="REJECTED"
    )
    assert out == "REJECTED"


def test_wrong_salt_is_rejected():
    """A value signed under one salt does not unsign under a different salt."""
    signed = sign_cookie_value(key="name", value="hello", salt="salt-a")

    out = unsign_cookie_value(
        key="name", signed_value=signed, salt="salt-b", default="REJECTED"
    )
    assert out == "REJECTED"


def test_wrong_key_is_rejected():
    """A value signed under one cookie name does not unsign under another."""
    signed = sign_cookie_value(key="name-a", value="hello", salt="salt")

    out = unsign_cookie_value(
        key="name-b", signed_value=signed, salt="salt", default="REJECTED"
    )
    assert out == "REJECTED"
