import pytest

from plain.runtime import settings
from plain.urls import absolute_url, reverse_absolute


def test_reverse_absolute():
    original = settings.BASE_URL
    try:
        settings.BASE_URL = "https://example.com"
        assert reverse_absolute("index") == "https://example.com/"
    finally:
        settings.BASE_URL = original


def test_absolute_url():
    original = settings.BASE_URL
    try:
        settings.BASE_URL = "https://example.com"
        assert absolute_url("/foo/bar/") == "https://example.com/foo/bar/"
    finally:
        settings.BASE_URL = original


def test_absolute_url_requires_base_url():
    with pytest.raises(ValueError, match="BASE_URL"):
        absolute_url("/foo/")
