from __future__ import annotations

import pytest

from plain.http import RedirectResponse


class TestRedirectResponse:
    def test_absolute_path_allowed(self):
        response = RedirectResponse("/home", status_code=302)
        assert response.url == "/home"

    def test_relative_path_allowed(self):
        response = RedirectResponse(".", status_code=302)
        assert response.url == "."

    def test_query_only_allowed(self):
        response = RedirectResponse("?success=true", status_code=302)
        assert response.url == "?success=true"

    def test_empty_url_allowed(self):
        response = RedirectResponse("", status_code=302)
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
            RedirectResponse(url, status_code=302)

    def test_external_url_allowed_with_flag(self):
        response = RedirectResponse(
            "https://example.com", status_code=302, allow_external=True
        )
        assert response.url == "https://example.com"

    @pytest.mark.parametrize("status_code", [301, 302, 303, 307, 308])
    def test_redirect_status_codes_allowed(self, status_code):
        response = RedirectResponse("/home", status_code=status_code)
        assert response.status_code == status_code

    @pytest.mark.parametrize("status_code", [200, 204, 404, 500])
    def test_non_redirect_status_code_rejected(self, status_code):
        with pytest.raises(ValueError, match="3xx redirect status"):
            RedirectResponse("/home", status_code=status_code)
