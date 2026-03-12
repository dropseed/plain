from __future__ import annotations

import pytest

from plain.http import RedirectResponse


class TestRedirectResponse:
    def test_absolute_path_allowed(self):
        response = RedirectResponse("/home")
        assert response.url == "/home"

    def test_relative_path_allowed(self):
        response = RedirectResponse(".")
        assert response.url == "."

    def test_query_only_allowed(self):
        response = RedirectResponse("?success=true")
        assert response.url == "?success=true"

    def test_empty_url_allowed(self):
        response = RedirectResponse("")
        assert response.url == ""

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.com",
            "http://evil.com",
            "ftp://evil.com",
            "//evil.com",
            "/\\evil.com",
            "\\\\evil.com",  # double backslash (browsers normalize to //)
            "\\/evil.com",  # backslash-slash (browsers normalize to //)
            " https://evil.com",  # leading space bypass
            "\thttps://evil.com",  # leading tab bypass
            "\n//evil.com",  # leading newline bypass
            "HtTpS://evil.com",  # mixed-case scheme
        ],
    )
    def test_external_url_rejected_by_default(self, url):
        with pytest.raises(ValueError, match="Unsafe redirect URL"):
            RedirectResponse(url)

    def test_external_url_allowed_with_flag(self):
        response = RedirectResponse("https://example.com", allow_external=True)
        assert response.url == "https://example.com"
