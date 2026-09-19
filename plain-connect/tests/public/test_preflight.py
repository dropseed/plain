from plain.connect.preflight import CheckConnectSecretKey
from plain.test import override_settings


def test_no_warning_when_pageviews_token_not_set():
    with override_settings(CONNECT_SECRET_KEY="", CONNECT_PAGEVIEWS_TOKEN=""):
        assert CheckConnectSecretKey().run() == []


def test_no_warning_when_secret_is_set():
    with override_settings(
        CONNECT_SECRET_KEY="app-secret", CONNECT_PAGEVIEWS_TOKEN="plain_pv_test"
    ):
        assert CheckConnectSecretKey().run() == []


def test_warns_when_pageviews_token_set_without_secret():
    with override_settings(
        CONNECT_SECRET_KEY="", CONNECT_PAGEVIEWS_TOKEN="plain_pv_test"
    ):
        results = CheckConnectSecretKey().run()
        assert len(results) == 1
        assert results[0].id == "connect.secret_key_missing"
        assert results[0].warning is True
        assert "CONNECT_PAGEVIEWS_TOKEN" in results[0].fix
