from plain.connect.preflight import CheckConnectSecretKey


def test_no_warning_when_pageviews_token_not_set(db, settings):
    settings.CONNECT_SECRET_KEY = ""
    settings.CONNECT_PAGEVIEWS_TOKEN = ""
    assert CheckConnectSecretKey().run() == []


def test_no_warning_when_secret_is_set(db, settings):
    settings.CONNECT_SECRET_KEY = "app-secret"
    settings.CONNECT_PAGEVIEWS_TOKEN = "plain_pv_test"
    assert CheckConnectSecretKey().run() == []


def test_warns_when_pageviews_token_set_without_secret(db, settings):
    settings.CONNECT_SECRET_KEY = ""
    settings.CONNECT_PAGEVIEWS_TOKEN = "plain_pv_test"
    results = CheckConnectSecretKey().run()
    assert len(results) == 1
    assert results[0].id == "connect.secret_key_missing"
    assert results[0].warning is True
    assert "CONNECT_PAGEVIEWS_TOKEN" in results[0].fix
