import hashlib
import hmac
import re
import time

from plain.connect.identity import sign_render_token
from plain.test import Client, override_settings

# Must match the literal endpoint id in tests/app/templates/page.html.
ENDPOINT_ID = "plain_sf_testid"
APP_SECRET = "app-secret"


def _input_value(content: bytes, name: str) -> str:
    pattern = rf'<input[^>]*\bname="{name}"[^>]*\bvalue="([^"]*)"'
    match = re.search(pattern.encode(), content)
    if match:
        return match.group(1).decode()
    if re.search(rf'<input[^>]*\bname="{name}"'.encode(), content):
        return ""
    raise AssertionError(f"no input name={name} in: {content!r}")


def _form_action(content: bytes) -> str:
    match = re.search(rb'<form[^>]*\baction="([^"]*)"', content)
    assert match, f"no form action in: {content!r}"
    return match.group(1).decode()


def test_fields_tag_always_renders_inputs():
    # Without a secret configured, values are empty but the inputs render —
    # the form is still posable, just without anti-spam scaffolding.
    response = Client().get("/")
    assert response.status_code == 200
    assert _input_value(response.content, "plain_connect_render_token") == ""
    assert _input_value(response.content, "plain_connect_identity") == ""
    assert b'name="plain_connect_check"' in response.content


def test_url_tag_renders_endpoint_id_into_action():
    response = Client().get("/")
    assert _form_action(response.content).endswith(f"/{ENDPOINT_ID}")


def test_url_tag_uses_configured_base():
    with override_settings(CONNECT_CLOUD_URL="https://custom.example"):
        response = Client().get("/")
        assert (
            _form_action(response.content)
            == f"https://custom.example/forms/{ENDPOINT_ID}"
        )


def test_render_token_signs_when_secret_is_set():
    with override_settings(CONNECT_SECRET_KEY=APP_SECRET):
        response = Client().get("/")
        rendered = _input_value(response.content, "plain_connect_render_token")
        assert rendered

        ts_str, _, mac = rendered.partition(".")
        expected = hmac.new(
            APP_SECRET.encode(), f"render-token:{ts_str}".encode(), hashlib.sha256
        ).hexdigest()
        assert hmac.compare_digest(expected, mac)
        assert abs(int(time.time()) - int(ts_str)) < 5


def test_render_token_is_fresh_per_render():
    with override_settings(CONNECT_SECRET_KEY=APP_SECRET):
        first = _input_value(Client().get("/").content, "plain_connect_render_token")
        time.sleep(1)
        second = _input_value(Client().get("/").content, "plain_connect_render_token")
        assert first != second


def test_sign_render_token_shape():
    token = sign_render_token(APP_SECRET, now=1700000000)
    ts_str, _, mac = token.partition(".")
    assert ts_str == "1700000000"
    expected = hmac.new(
        APP_SECRET.encode(), b"render-token:1700000000", hashlib.sha256
    ).hexdigest()
    assert mac == expected


def test_sign_render_token_empty_without_secret():
    assert sign_render_token("") == ""
